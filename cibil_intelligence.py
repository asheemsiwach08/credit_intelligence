from pydantic import BaseModel
from typing import List, Dict, Any
import PyPDF2
import json
import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import Json

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv
from data_loaders import load_data
from prompts import DEFAULT_CIBIL_PROMPT
from cibil_base_model import Cibil_Report_Format
from tenacity import retry, stop_after_attempt, wait_random_exponential

# ------------------------------------------------------------------------------------------- #
# Configuration settings
# ------------------------------------------------------------------------------------------- #
# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

@dataclass(frozen=True)
class Settings:
    """Runtime secrets + toggles loaded from env vars.

    * `openai_key`   – OpenAI API key (required)
    * `s3_bucket`    – S3 bucket name for PDF uploads (optional)
    * `pg_dsn`       – libpq‑style DSN for PostgreSQL (optional; built from
                       PG_HOST etc.)
    * `pg_table`     – table name for persisting reports
    """

    openai_key: str
    s3_bucket: Optional[str]
    pg_dsn: Optional[str]
    pg_table: str

    @staticmethod
    def load() -> "Settings":
        load_dotenv()

        # --- required secret ------------------------------------------------
        key = os.getenv("CIBIL_OPENAI_KEY")
        if not key:
            raise RuntimeError(f"Missing required Openai Key")

        # --- optional S3 bucket --------------------------------------------
        bucket = os.getenv("ENV_S3_BUCKET")

        # --- optional Postgres DSN -----------------------------------------
        host = os.getenv("ENV_POSTGRES_HOST")
        if host:
            port = os.getenv("ENV_POSTGRES_PORT", "5432")
            user = os.getenv("ENV_POSTGRES_USER", "postgres")
            pwd = os.getenv("ENV_POSTGRES_PASSWORD", "")
            dbname = os.getenv("ENV_POSTGRES_DB", "postgres")
            dsn = f"host={host} port={port} dbname={dbname} user={user} password={pwd}"
        else:
            dsn = None

        # --- table name -----------------------------------------------------
        table = os.getenv("ENV_POSTGRES_TABLE", "cibil_intelligence")

        return Settings(
            openai_key=key,
            s3_bucket=bucket,
            pg_dsn=dsn,
            pg_table=table,
        )


# ------------------------------------------------------------------------------------------- #
# Prompt to the user for raw CIBIL report data
# ------------------------------------------------------------------------------------------- #
DEFAULT_CIBIL_PROMPT = """You are a financial data analyst and reporting agent. Your task is to convert raw CIBIL report data into a clean, structured, and intelligence-based credit report. The output should be optimized for review by lenders, underwriters, or financial institutions.

Take the raw data input provided, and perform the following:

1. Extract key information such as:
   - Customer details (name, DOB, PAN)
   - CIBIL score and status
   - Summary of accounts (active, closed, overdue, written-off)
   - Detailed credit enquiry history (last 6 months)
   - Per-account details (type, ownership, balance, DPD, payment history)
   - Any red flags (e.g., high DPD, written-off accounts, frequent enquiries)

2. Analyze the data to provide:
   - Risk assessment (Low, Moderate, High)
   - Score interpretation (based on CIBIL score range)
   - Lending recommendation or caution

3. Present the output in a structured JSON format following this schema:
   - report_summary
   - risk_analysis
   - account_summary
   - credit_enquiries
   - account_details
   - remarks

4. Ensure all values are normalized (e.g., dates in YYYY-MM-DD, amounts in numbers).

5. Be intelligent in data cleaning — deduplicate entries, handle inconsistencies, and flag incomplete fields.

6. Do not hallucinate or assume missing fields; mark such fields clearly as `"unknown"` or `null`.

Output only the final structured report in JSON format.

Begin processing the following raw data:

{{RAW_CIBIL_REPORT_DATA_HERE}}
"""

# ------------------------------------------------------------------------------------------- #
# Base model for structured data
# ------------------------------------------------------------------------------------------- #
# Define a strict schema for dpd_30_60_90_plus with additionalProperties set to false
class PaymentHistorySummary(BaseModel):
    dpd_30_60_90_plus: dict
    recent_dpd_flag: bool  # Flag to indicate if recent DPD is a concern

    class Config:
        extra = 'forbid'  # Ensure no extra properties in the PaymentHistorySummary

    # Explicitly define dpd_30_60_90_plus schema with additionalProperties set to false
    # @property
    def dpd_30_60_90_plus(self):
        return {
            "type": "object",
            "properties": {
                "30_days": { "type": "integer" },
                "60_days": { "type": "integer" },
                "90_plus_days": { "type": "integer" }
            },
            "additionalProperties": False  # Ensure no extra properties allowed here
        }

class AccountDetail(BaseModel):
    account_type: str  # e.g., "Credit Card", "Personal Loan", etc.
    account_number: str  # masked string
    ownership: str  # "Individual", "Joint", etc.
    opened_date: str  # YYYY-MM-DD format
    last_payment_date: Optional[str]  # YYYY-MM-DD format, Optional
    current_balance: float  # Balance remaining in the account
    sanctioned_amount: float  # Total sanctioned amount for the account
    repayment_tenure: Optional[int]  # in months
    account_status: str  # "Active", "Closed", etc.
    # payment_history_summary: PaymentHistorySummary  # Detailed history of payments

    class Config:
        extra = 'forbid'

class EnquiryDetail(BaseModel):
    date: str  # Date in YYYY-MM-DD format
    enquirer_name: str
    enquiry_purpose: str

    class Config:
        extra = 'forbid'

class UserDetails(BaseModel):
    user_name: str
    date_of_birth: str
    pan: str
    report_generated_date: str
    cibil_score: Optional[int]
    score_status: str  # "Available", "Not Available", "NA"

    class Config:
        extra = 'forbid'

class RiskAnalysis(BaseModel):
    risk_category: str  # "Low", "Moderate", "High"
    score_interpretation: str  # Interpretation of the CIBIL score
    suggested_action: str  # Suggest action like "Approved", "Under Review", "Reject"

    class Config:
        extra = 'forbid'

class AccountSummary(BaseModel):
    total_accounts: int
    active_accounts: int
    closed_accounts: int
    overdue_accounts: int
    written_off_accounts: int

    class Config:
        extra = 'forbid'

class CreditEnquiries(BaseModel):
    total_enquiries_last_6_months: int
    high_frequency_flag: bool  # Flag if there are frequent enquiries
    enquiry_details: List[EnquiryDetail]  # List of detailed enquiries

    class Config:
        extra = 'forbid'

class Remarks(BaseModel):
    critical_flags: List[str]  # List of critical flags like "Frequent Enquiries"
    general_observations: str  # Other observations or remarks

    class Config:
        extra = 'forbid'

class Cibil_Report_Format(BaseModel):
    user_details: UserDetails
    risk_analysis: RiskAnalysis
    account_summary: AccountSummary
    credit_enquiries: CreditEnquiries
    account_details: List[AccountDetail]
    remarks: Remarks
    summary_report: str

    class Config:
        extra = 'forbid'

    def generate_summary_report(self) -> str:
        """Return a human‑readable one‑pager summarising the bureau data."""
        rs, ra, acc, ce, rem = (
            self.report_summary,
            self.risk_analysis,
            self.account_summary,
            self.credit_enquiries,
            self.remarks,
        )

        summary = (
            f"--- CIBIL Report Summary ---\n"
            f"1. **CIBIL Score**: {rs.cibil_score} ({rs.score_status})\n"
            f"   • Falls in the **{ra.risk_category}** bucket.\n"
            f"2. **Risk Analysis**\n"
            f"   • Interpretation : {ra.score_interpretation}\n"
            f"   • Suggested action: {ra.suggested_action}\n"
            f"3. **Accounts**\n"
            f"   • Total   : {acc.total_accounts}\n"
            f"   • Active  : {acc.active_accounts}\n"
            f"   • Overdue : {acc.overdue_accounts}\n"
            f"4. **Credit Enquiries (6 mo)**\n"
            f"   • Count   : {len(ce.enquiry_details)}\n"
            f"   • High frequency flag: {ce.high_frequency_flag}\n"
            f"5. **Remarks**\n"
            f"   • Critical flags    : {', '.join(rem.critical_flags) or 'None'}\n"
            f"   • Observations      : {rem.general_observations}\n"
        )
        return summary

# ------------------------------------------------------------------------------------------- #
# Data Loader and Validation
# ------------------------------------------------------------------------------------------- #

def load_json(file_path: str) -> str:
    """Load and validate JSON data from a file."""
    if not file_path.lower().endswith('.json'):
        raise ValueError("Provided file is not a JSON file.")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, (dict, list)):
                raise ValueError("Invalid JSON format: Must be dict or list.")
            logging.info("JSON data loaded successfully.")
            return str(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to read JSON file: {e}")


def extract_text_from_pdf(file_path: str, password: str = "") -> str:
    """Extract text from a PDF file with validation and error handling."""
    if not file_path.lower().endswith('.pdf'):
        raise ValueError("Provided file is not a PDF.")

    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            if reader.is_encrypted:
                logging.info("PDF is encrypted. Attempting decryption.")
                if not reader.decrypt(password):
                    raise PermissionError("Incorrect password or failed to decrypt PDF.")

            if not reader.pages:
                raise ValueError("PDF file is empty or unreadable.")

            text = ''
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text() or ''
                logging.info(f"Extracted text from page {page_num + 1}")
                text += page_text
            return text.strip()
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {e}")



def load_data(file_path: str | Path, password: Optional[str] = None) -> str:
    """
    Load data from a .json or .pdf file.

    Args:
        file_path: Path to a JSON or PDF file.
        password : Password for encrypted PDFs (ignored for JSON).

    Returns:
        The file contents as a string.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path.resolve()}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"File is not readable: {path.resolve()}")

    ext = path.suffix.lower()
    if ext == ".json":
        if password:
            raise ValueError("Password argument is only valid for PDF input.")
        return load_json(str(path))

    if ext == ".pdf":
        if password is None:
            raise ValueError("Encrypted PDF requires a password.")
        return extract_text_from_pdf(str(path), password=password)

    raise ValueError(
        f"Unsupported file type '{ext}'. Only '.json' and '.pdf' are accepted."
    )

# ------------------------------------------------------------------------------------------- #
# Persistent Layer
# ------------------------------------------------------------------------------------------- #

class DataPersister:
    """Optional persistence layer – S3 for PDFs, PostgreSQL for JSON reports."""

    def __init__(self, *, settings: Settings):
        self._s3_bucket = settings.s3_bucket
        self._pg_dsn = settings.pg_dsn
        self._pg_table = settings.pg_table

        self._s3 = boto3.client("s3") if self._s3_bucket else None
        self._pg_conn = psycopg2.connect(self._pg_dsn) if self._pg_dsn else None
        if self._pg_conn:
            self._pg_conn.autocommit = True

        # ---------------------- S3 ---------------------- #
    def upload_pdf(self, path: Path) -> None:
        if not self._s3_bucket or not self._s3:
            logging.debug("S3 bucket not configured – skipping PDF upload")
            logging.info("Skipping PDF upload------------->")
            return

        key = f"raw-pdfs/{path.stem}-{datetime.now(timezone.utc).isoformat()}.pdf"
        logging.info("Uploading %s → s3://%s/%s", path, self._s3_bucket, key)
        try:
            self._s3.upload_file(str(path), self._s3_bucket, key)
        except (BotoCoreError, ClientError):
            logging.exception("Failed to upload %s to S3", path)
            raise

    # ------------------- PostgreSQL ------------------- #
    def save_json_report(self, report_json: str) -> None:
        if not self._pg_conn:
            logging.debug("PostgreSQL DSN not configured – skipping JSON persistence")
            logging.info("Skipping JSON persistence------------->")
            return

        insert_sql = (
            f"INSERT INTO {self._pg_table} (report_id, created_at, report) "
            "VALUES (%s, %s, %s)"
        )
        report_id = "DDIPR5958G9663" #str(uuid4())
        created_at = datetime.now(timezone.utc)
        data = Json(json.loads(report_json))
        logging.info("Persisting report %s to table %s", report_id, self._pg_table)
        with self._pg_conn.cursor() as cur:
            cur.execute(insert_sql, (report_id, created_at, data))

# ------------------------------------------------------------------------------------------- #
# Core generator
# ------------------------------------------------------------------------------------------- #

class CibilReportGenerator:
    """Wrapper around the OpenAI client encapsulating retries, timeouts and
    prompt fallbacks. You can extend this with async APIs or streaming if your
    use‑case requires lower latency or partial responses.
    """

    def __init__(self, openai_key: str) -> None:
        self._client = OpenAI(api_key=openai_key)

    @retry(wait=wait_random_exponential(min=5, max=60), stop=stop_after_attempt(5))
    def _call_llm(
        self,
        *,
        raw_data: str,
        prompt: str,
        model: str = "gpt-4.1-nano-2025-04-14",  # Update to model/SKU of your choice
    ) -> str:
        """Low‑level helper that actually calls the model. Retry decorator
        handles transient network/5xx errors with jittered exponential back‑off
        (AWS‑style) to play nicely with rate limits.
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": raw_data},
        ]
        logging.debug("Sending %d messages to model=%s", len(messages), model)

        try:
            response = self._client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=Cibil_Report_Format,
                timeout=60,  # seconds
            )
        except OpenAIError:
            logging.exception("OpenAI API error")
            raise

        return response.choices[0].message.content

    def generate(self, raw_data: str, prompt_override: Optional[str] = None) -> str:
        """Generate report, optionally injecting an override prompt provided by
        the front‑end. Falls back to the default expert prompt shipped with the
        backend if none is given.
        """
        prompt = prompt_override.strip() if prompt_override else DEFAULT_CIBIL_PROMPT
        return self._call_llm(raw_data=raw_data, prompt=prompt)

# ------------------------------------------------------------------------------------------- #
# Data input helpers
# ------------------------------------------------------------------------------------------- #

def load_input(source: str | Path, *, password: Optional[str] = None) -> tuple[str, Optional[Path]]:
    maybe_path = Path(source)
    if maybe_path.exists():
        logging.debug("Loading file %s via data_loaders.load_data()", maybe_path)
        raw = load_data(file_path=str(maybe_path), password=password)
        return raw, maybe_path if maybe_path.suffix.lower() == ".pdf" else None

    logging.debug("Interpreting input as raw JSON payload")
    try:
        json.loads(source)  # fast syntax check only
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Input must be a .pdf/.json file path or a valid JSON payload string"
        ) from exc
    return source, None

# ------------------------------------------------------------------------------------------- #
# CLI
# ------------------------------------------------------------------------------------------- #
def run_cibil_pipeline(
    input_spec: str,
    prompt_override: Optional[str] = None,
    pdf_password: Optional[str] = None,
) -> str:
    """
    Core business logic shared by both Lambda and local tests.
    """
    settings = Settings.load()
    persister = DataPersister(settings=settings)

    # Resolve prompt override if it's a file path
    if prompt_override:
        p = Path(prompt_override)
        if p.exists():
            prompt_override = p.read_text(encoding="utf‑8")
            logging.debug("Prompt override loaded from %s", p)

    # Load raw text (and possibly PDF path) from the input
    raw_text, pdf_path = load_input(input_spec, password=pdf_password)

    generator = CibilReportGenerator(openai_key=settings.openai_key)
    logging.info("Generating CIBIL intelligence report…")
    report_json = generator.generate(raw_data=raw_text,
                                     prompt_override=prompt_override)

    # Persist results
    persister.save_json_report(report_json=report_json)
    # Optionally keep the PDF in S3 as well
    # if pdf_path:
    #     persister.upload_pdf(pdf_path)

    return report_json


# ----------------------------- AWS Lambda entry‑point ------------------------------
def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Expected `event` keys:
        input  : str  (S3 URI, local path, or raw JSON)
        prompt : str  (optional prompt override, raw or S3/path)
        pdf_password : str (optional)
    """
    try:
        report = run_cibil_pipeline(
            input_spec=event["input"],
            prompt_override=event.get("prompt"),
            pdf_password=event.get("pdf_password"),
        )
        return {
            "statusCode": 200,
            "body": json.dumps(report),   # API Gateway‑friendly
        }
    except Exception as exc:
        logging.exception("Lambda invocation failed")
        return {
            "statusCode": 500,
            "body": str(exc),
        }




