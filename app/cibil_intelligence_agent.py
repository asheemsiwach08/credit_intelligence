import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Union, Tuple, List

import psycopg2

import boto3
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from app.data_loaders import load_data
from app.prompts import prompt_v2
from app.cibil_base_model import Cibil_Report_Format
from app.utils.queries import cibil_report_insert_query, UPDATE_CIBIL_REPORT
from tenacity import retry, stop_after_attempt, wait_random_exponential

# ------------------------------------------------------------------------------------------- #
                                    # Configuration
# ------------------------------------------------------------------------------------------- #
# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

@dataclass(frozen=True)
class Settings:
    """
    Runtime secrets + toggles loaded from env vars.

    * `openai_key`      – OpenAI API key (required)
    * `s3_bucket`       – S3 bucket name for PDF uploads (optional)
    * `aws_access_key`  – AWS Access Key ID for S3 (optional)
    * `aws_secret_key`  – AWS Secret Access Key for S3 (optional)
    * `aws_region`      – AWS Region for S3 (optional)
    * `pg_dsn`          – libpq-style DSN for PostgreSQL (optional)
    * `pg_table`        – table name for persisting reports
    """

    openai_key: str
    s3_bucket: Optional[str]
    aws_access_key: Optional[str]
    aws_secret_key: Optional[str]
    aws_region: Optional[str]
    pg_dsn: Optional[str]
    pg_table: str

    @staticmethod
    def load() -> "Settings":
        load_dotenv()

        # --- required OpenAI key ---
        key = os.getenv("CIBIL_OPENAI_KEY")
        if not key:
            raise RuntimeError("Missing required OpenAI key (CIBIL_OPENAI_KEY)")

        # --- optional S3 config ---
        bucket = os.getenv("ENV_S3_BUCKET")
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION")

        # --- optional Postgres DSN ---
        host = os.getenv("ENV_POSTGRES_HOST")
        if host:
            port = os.getenv("ENV_POSTGRES_PORT", "5432")
            user = os.getenv("ENV_POSTGRES_USER", "postgres")
            pwd = os.getenv("ENV_POSTGRES_PASSWORD", "")
            dbname = os.getenv("ENV_POSTGRES_DB", "postgres")
            dsn = f"host={host} port={port} dbname={dbname} user={user} password={pwd}"
            logging.info(f"Postgres DSN: {dsn}")
        else:
            dsn = None

        # --- default table name ---
        table = os.getenv("ENV_POSTGRES_TABLE", "cibil_intelligence")

        return Settings(
            openai_key=key,
            s3_bucket=bucket,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_region=aws_region,
            pg_dsn=dsn,
            pg_table=table,
        )

# ------------------------------------------------------------------------------------------- #
                                    # Persistent Layer
# ------------------------------------------------------------------------------------------- #
class DataPersister:

    def __init__(self, *, settings: Settings):
        self._pg_dsn = settings.pg_dsn
        self._pg_table = settings.pg_table

        self._pg_conn = psycopg2.connect(self._pg_dsn) if self._pg_dsn else None
        if self._pg_conn:
            self._pg_conn.autocommit = True

        # S3
        self._s3_bucket = settings.s3_bucket
        self._s3_client = (
            boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key,
                aws_secret_access_key=settings.aws_secret_key,
                region_name=settings.aws_region,
            )
            if settings.s3_bucket
            else None
            )

    # ---------------- S3 Upload ---------------- #
    def upload_pdf(self, file_object: object, report_id: str) -> None:
        """Upload the PDF to S3 using the report ID as the object name."""
        if not self._s3_client or not self._s3_bucket:
            logging.debug("S3 not configured – skipping PDF upload")
            return

        # if not file_path.exists():
        #     logging.warning("File %s does not exist – cannot upload", file_path)
        #     return

        object_key = f"/users/credit-score/{report_id}.pdf"
        # logging.info("Uploading %s to S3 bucket %s as %s", file_path, self._s3_bucket, object_key)

        try:
            self._s3_client.upload_fileobj(
                Fileobj=file_object,
                Bucket=self._s3_bucket,
                Key=object_key,
            )
            logging.debug("File pushed to the S3 bucket.")
        except Exception as e:
            logging.error("Failed to upload file to S3: %s", e)

    # ------------------- PostgreSQL ------------------- #
    def save_json_report(self, data_values: List[str]) -> None:
        if not self._pg_conn:
            logging.debug("PostgreSQL DSN not configured – skipping JSON persistence")
            return

        logging.info("Persisting report to table %s", self._pg_table)
        pan = data_values[0]  # assuming PAN is always the first value
        insert_query = cibil_report_insert_query
        update_query = UPDATE_CIBIL_REPORT

        with self._pg_conn.cursor() as cur:
            # 1. Check if PAN already exists
            cur.execute(f"SELECT 1 FROM cibil_intelligence WHERE pan = %s", (pan,))
            exists = cur.fetchone()

            if exists:
                update_values =  data_values[1:] + [pan]  # all except PAN, then PAN at end
                cur.execute(update_query, update_values)
                logging.info("Updated existing record for PAN: %s", pan)
            else:
                cur.execute(insert_query, data_values)
                logging.info("Inserted new record for PAN: %s", pan)

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
                timeout=60,  # seconds,
                temperature=0,
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
        prompt = prompt_override.strip() if prompt_override else prompt_v2
        return self._call_llm(raw_data=raw_data, prompt=prompt)

# ------------------------------------------------------------------------------------------- #
                                    # Data input helpers
# ------------------------------------------------------------------------------------------- #
def load_input(
    source: Union[str, Path],
    *,
    password: Optional[str] = None,
    boto3_session: boto3.Session | None = None,
) -> Tuple[str, Optional[Path]]:
    """
    Accepts:
      • Local .pdf /.json path
      • s3://bucket/key URI
      • Raw JSON payload string

    Returns
    -------
    (raw_content, pdf_path_or_None)
        raw_content : str
            Extracted text (PDF) or JSON string.
        pdf_path_or_None : pathlib.Path | None
            Local Path for a disk‑based PDF; None for S3 or JSON strings.
    """
    # -- Local file -------------------------------------------------------- #
    maybe_path = Path(source)
    if maybe_path.exists():
        logging.debug("Loading local file %s via load_data()", maybe_path)
        raw = load_data(str(maybe_path), password=password)
        return raw, maybe_path if maybe_path.suffix.lower() == ".pdf" else None

    # -- S3 URI ----------------------------------------------------------- #
    if isinstance(source, str) and source.startswith("s3://"):
        logging.debug("Loading S3 object %s via load_data()", source)
        raw = load_data(source, password=password, boto3_session=boto3_session)
        return raw, None

    # -- Raw JSON payload string ------------------------------------------- #
    logging.debug("Interpreting input as raw JSON payload string")
    print(source,"------cibil intelligence")
    try:
        json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Input must be a .pdf/.json file path, an s3:// URI, or a valid JSON payload string."
        ) from exc

    return source, None

# ------------------------------------------------------------------------------------------- #
                                        # CLI
# ------------------------------------------------------------------------------------------- #
#
# def build_arg_parser() -> argparse.ArgumentParser:
#     p = argparse.ArgumentParser(description="Generate a CIBIL intelligence report.")
#     p.add_argument("input", help="Path, s3:// URI, or JSON string.")
#     p.add_argument(
#         "-p", "--prompt",
#         help=(
#             "Override prompt: either a file path or literal string supplied "
#             "by the front‑end. If absent, a sturdy expert prompt shipped with "
#             "the backend is used."
#         ),
#     )
#     p.add_argument("--pdf-password", help="Password for PDF (if encrypted)")
#     p.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity")
#     return p
#
#
# def main(argv: Optional[list[str]] = None) -> None:
#     args = build_arg_parser().parse_args(argv)
#
#     settings = Settings.load()
#     persister = DataPersister(settings=settings)
#
#     # Resolve prompt override if provided
#     prompt_override: Optional[str] = None
#     if args.prompt:
#         prompt_source = Path(args.prompt)
#         prompt_override = (
#             prompt_source.read_text(encoding="utf-8") if prompt_source.exists() else args.prompt
#         )
#         logging.debug("Prompt override provided (length=%d)", len(prompt_override))
#
#     raw_text, pdf_path = load_input(args.input, password=args.pdf_password)
#
#     generator = CibilReportGenerator(openai_key=settings.openai_key)
#     logging.info("Generating CIBIL intelligence report…")
#
#     try:
#         report_json = generator.generate(raw_data=raw_text, prompt_override=prompt_override)
#         print(report_json)
#         persister.save_json_report(report_json=report_json)
#     except Exception:
#         logging.exception("Failed to generate report")
#         sys.exit(1)
#
#
# # ------------------------------------------------------------------------------------------- #
# if __name__ == "__main__":
#     main()
