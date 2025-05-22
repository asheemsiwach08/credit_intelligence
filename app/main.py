import json
import logging
import uuid
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from app.cibil_intelligence_agent import CibilReportGenerator, DataPersister, load_input, Settings
from app.data_loaders import extract_text_from_pdf
from app.utils.data_utils import safe_get, try_parse_date

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
app = FastAPI()

@app.post("/generate_cibil_report")
async def generate_cibil_report(
        file: Optional[UploadFile] = File(None),
        source_url: Optional[str] = Form(None),
        prompt: Optional[str] = Form(None),
        pdf_password: Optional[str] = Form(None)):
    """
    Exactly one of **file** or **source_url** must be provided.

    • file           → standard multipart upload
    • source_url     → s3://bucket/key, local path on server, or raw JSON payload
    """
    logging.info("Done till here.......")
    try:
        if bool(file) == bool(source_url):  # XOR check
            raise HTTPException(
                status_code=400,
                detail="Provide either an uploaded file or source_url, but not both."
            )

        # ───────────────────────────────────────────────────────────────── #
        # 1.  Resolve prompt override (file path or direct text)
        # ───────────────────────────────────────────────────────────────── #
        prompt_override: Optional[str] = None
        if prompt:
            prompt_source = Path(prompt)
            prompt_override = (
                prompt_source.read_text(encoding="utf-8") if prompt_source.exists() else prompt
            )
            logging.debug("Prompt override provided (length=%d)", len(prompt_override))

        # ───────────────────────────────────────────────────────────────── #
        # 2.  Obtain raw_text & pdf_path using the new unified loaders
        # ───────────────────────────────────────────────────────────────── #
        if file:
            # Read the uploaded bytes into memory
            uploaded_bytes = await file.read()

            # Decide how to interpret the upload
            if file.filename.lower().endswith(".pdf"):
                raw_text = extract_text_from_pdf(uploaded_bytes, password=pdf_password or "")
                logging.info("We are in the pdf.")
                pdf_path = None  # we never wrote it to disk
            elif file.filename.lower().endswith(".json"):
                raw_text = uploaded_bytes.decode("utf-8")
                pdf_path = None
            else:
                raise HTTPException(400, "Only .pdf or .json uploads are accepted.")
        else:
            # Delegate everything (local path, S3 URI, or raw JSON string)
            raw_text, pdf_path = load_input(source_url, password=pdf_password)

        logging.info("DONe with the pdf data.")

        # ───────────────────────────────────────────────────────────────── #
        # 3.  Business logic
        # ───────────────────────────────────────────────────────────────── #
        logging.info("Going for settings")
        settings = Settings.load()
        logging.info("Going for database")
        persister = DataPersister(settings=settings)

        # Generate Report and Save to Database
        logging.info("Going for API")
        generator = CibilReportGenerator(openai_key=settings.openai_key)
        report_json = generator.generate(raw_data=raw_text, prompt_override=prompt)
        logging.info("API did its work")

        # Values for Database
        report_json = json.loads(report_json)
        user_details = report_json.get("user_details", {})
        risk_analysis = report_json.get("risk_analysis", {})
        account_summary = report_json.get("account_summary", {})
        credit_enquiries = report_json.get("credit_enquiries", {})
        remarks = report_json.get("remarks", {})
        summary_report = report_json.get("summary_report", {})
        logging.info("Json is working")
        print(user_details)

        if not user_details.get("user_name") or not user_details.get("pan"):
            raise HTTPException(status_code=422, detail="Missing user_name or PAN")

        # Step 1: Extract all 25 values
        data_values = [
            # user_details
            safe_get(user_details, "pan"),
            safe_get(user_details, "user_name"),
            try_parse_date("date_of_birth"),
            try_parse_date("report_generated_date"),
            safe_get(user_details, "cibil_score"),
            safe_get(user_details, "score_status"),

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

            # summary_report
            str(summary_report)
        ]

        persister.save_json_report(data_values=data_values)

        return JSONResponse(content=report_json)

    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
