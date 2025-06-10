import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from fastapi import UploadFile, HTTPException

from app.utils.data_loaders import extract_text_from_pdf
from app.utils.data_utils import (
    safe_get,
    try_parse_date,
)

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# =============================================================================
# Helper utilities
# =============================================================================
def _resolve_prompt(prompt: Optional[str]) -> Optional[str]:
    """Return the prompt text, supporting *file path* or *inline text*.

    If *prompt* is a valid file path, the file content is returned; otherwise
    the raw string is returned unchanged.
    """
    if not prompt:
        return None

    prompt_path = Path(prompt)
    if prompt_path.exists():
        logging.debug("Reading prompt from file: %s", prompt_path)
        return prompt_path.read_text(encoding="utf-8")

    logging.debug("Using inline prompt text (length=%d)", len(prompt))
    return prompt


from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException
import logging

def _read_upload(
    filename: str,
    upload_bytes: bytes,
    pdf_password: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Read an uploaded PDF or JSON file, return its raw text content and None for path (in-memory),
    and upload the file to S3 regardless of type.
    """


    try:
        # Process the content
        if filename.endswith(".pdf"):
            raw_text = extract_text_from_pdf(upload_bytes, password=pdf_password or "")
            return raw_text, None

        elif filename.endswith(".json"):
            return upload_bytes.decode("utf-8"), None

        else:
            raise HTTPException(400, detail="Only .pdf or .json uploads are accepted.")

    except Exception as e:
        logging.error("Error processing uploaded file: %s", e)
        raise HTTPException(500, detail="Error processing uploaded file.")


def _validate_user_details(user_details: Dict[str, Any]) -> None:
    """Ensure *user_name* or *pan* are present; raise 422 otherwise."""
    if not user_details.get("user_name") or not user_details.get("pan"):
        logging.debug("Missing user_name or PAN details.")
        raise HTTPException(status_code=422, detail="Missing user_name or PAN")


def _extract_data_values(report: Dict[str, Any]) -> List[Any]:
    """Flatten the report into the 25‑column *data_values* list expected
    by :pyclass:`app.cibil_intelligence_agent.DataPersister`.
    """
    user_details = report.get("user_details", {})
    credit_score = safe_get(report, "credit_score", {})
    risk_analysis = report.get("risk_analysis", {})
    account_summary = report.get("account_summary", {})
    credit_enquiries = report.get("credit_enquiries", {})
    remarks = report.get("remarks", {})
    summary_report = report.get("summary_report", {})

    return [
        # user_details
        safe_get(user_details, "pan"),
        safe_get(user_details, "user_name"),
        try_parse_date(user_details.get("date_of_birth")),
        safe_get(user_details, "gender"),
        safe_get(user_details, "age"),
        safe_get(user_details, "phone_number"),
        safe_get(user_details, "email_address"),
        try_parse_date(credit_score.get("report_generated_date")),
        safe_get(credit_score, "credit_score"),
        safe_get(credit_score, "score_status"),

        # risk_analysis
        safe_get(risk_analysis, "risk_category"),
        safe_get(risk_analysis, "score_interpretation"),
        safe_get(risk_analysis, "suggested_action"),

        # account_summary
        safe_get(account_summary, "total_accounts"),
        safe_get(account_summary, "active_accounts"),
        safe_get(account_summary, "closed_accounts"),
        safe_get(account_summary, "overdue_accounts"),
        safe_get(account_summary, "written_off_accounts"),

        # credit_enquiries
        safe_get(credit_enquiries, "total_enquiries_last_6_months"),
        safe_get(credit_enquiries, "high_frequency_flag"),
        str(safe_get(credit_enquiries, "enquiry_details")),

        # remarks
        str(safe_get(remarks, "critical_flags")),
        safe_get(remarks, "general_observations"),

        # summary_report (as JSON‑serialised string)
        json.dumps(summary_report, default=str),
    ]
