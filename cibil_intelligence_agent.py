import argparse
import json
import os
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

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
# Configuration
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

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate a CIBIL intelligence report.")
    p.add_argument("input", help="Path to PDF/JSON file or raw JSON string")
    p.add_argument(
        "-p", "--prompt",
        help=(
            "Override prompt: either a file path or literal string supplied "
            "by the front‑end. If absent, a sturdy expert prompt shipped with "
            "the backend is used."
        ),
    )
    p.add_argument("--pdf-password", help="Password for PDF (if encrypted)")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity")
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    settings = Settings.load()
    persister = DataPersister(settings=settings)

    # Resolve prompt override if provided
    prompt_override: Optional[str] = None
    if args.prompt:
        prompt_source = Path(args.prompt)
        prompt_override = (
            prompt_source.read_text(encoding="utf-8") if prompt_source.exists() else args.prompt
        )
        logging.debug("Prompt override provided (length=%d)", len(prompt_override))

    raw_text, pdf_path = load_input(args.input, password=args.pdf_password)
    if pdf_path:
        persister.upload_pdf(pdf_path)

    generator = CibilReportGenerator(openai_key=settings.openai_key)
    logging.info("Generating CIBIL intelligence report…")

    try:
        report_json = generator.generate(raw_data=raw_text, prompt_override=prompt_override)
        print(report_json)
        # persister.save_json_report(report_json=report_json)
        print(report_json)
    except Exception:
        logging.exception("Failed to generate report")
        sys.exit(1)


# ------------------------------------------------------------------------------------------- #
if __name__ == "__main__":
    main()



