from datetime import datetime
import json
import logging
from io import BytesIO

from typing import Optional, Dict, Any

from fastapi.responses import JSONResponse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.credit_intelligence_agent import CreditReportGenerator, DataPersister, load_input, Settings
from app.utils.data_utils import calculate_recent_payments_by_lender, generate_file_name
from app.utils.error_handling import PDFReadError, BadURLError, OpenAITimeout, ValidationError
from app.utils.queries import EXTRACT_PAN_DETAILS
from app.views.credit_intelligence import _read_upload, _resolve_prompt, _validate_user_details, _extract_data_values

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
app = FastAPI()
# origins = ["*"]
# app.add_middleware(CORSMiddleware, allow_origins=origins,
#                    allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


# Sub-app for CREDIT routes
credit_app = FastAPI()
origins = ["*"]
credit_app.add_middleware(CORSMiddleware, allow_origins=origins,
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


# =============================================================================
# Route handlers
# =============================================================================
# @app.post("/generate_cibil_report", response_class=JSONResponse)
@credit_app.post("/generate_credit_report", response_class=JSONResponse)
async def generate_credit_report(
        file: Optional[UploadFile] = File(None),
        source_url: Optional[str] = Form(None),
        fallback_id: Optional[str] = Form(None),
        prompt: Optional[str] = Form(None),
        pdf_password: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
):
    """Generate a CREDIT intelligence report from either an uploaded file or
    a source URL/raw JSON.

    Exactly one of file or source_url must be supplied; supplying both
    (or neither) yields a 400.
    """
    settings = Settings.load()
    persister = DataPersister(settings=settings)

    input_modes = sum([bool(file), bool(source_url), bool(fallback_id)])

    if input_modes > 1:
        raise HTTPException(400, detail="Provide only one input: file, source_url(S3) or fallback_id.")

    # --------------------------------------------------------------------
    # 1. Obtain raw text (or fallback from DB) from the provided source
    # --------------------------------------------------------------------
    try:
        if file:
            filename = file.filename.lower()
            upload_bytes = file.file.read()
            file.file.seek(0)
            raw_text, pdf_path = _read_upload(filename=filename, upload_bytes=upload_bytes, pdf_password=pdf_password)
        elif source_url:
            raw_text, pdf_path = load_input(source_url, password=pdf_password)
        else:
            if not fallback_id:
                raise HTTPException(400,
                                    detail="No file or source_url provided. Provide fallback_id to use stored data.")

            # Check the validation of the fallback_id
            if len(fallback_id) != 10:
                raise HTTPException(400, detail="Invalid fallback_id. Please provide a valid 10-digit PAN ID.")

            # Extract data from the DB using the provided fallback_id
            pan_query = (EXTRACT_PAN_DETAILS, (fallback_id.upper(),))
            raw_text = persister.fetch_data_from_db(query=pan_query)
            pdf_path = None
    except (PDFReadError, BadURLError, Exception) as exc:
        raise HTTPException(400, detail=str(exc))

    # --------------------------------------------------------------------
    # 2. Resolve the user‑supplied prompt override
    # --------------------------------------------------------------------
    prompt_override = _resolve_prompt(prompt)

    # --------------------------------------------------------------------
    # 3. Generate the report via OpenAI‑powered *CreditReportGenerator*
    # --------------------------------------------------------------------
    try:
        generator = CreditReportGenerator(openai_key=settings.openai_key)
        report_json_str = generator.generate(raw_data=raw_text, prompt_override=prompt_override)
        report: Dict[str, Any] = json.loads(report_json_str)
    except (OpenAITimeout, json.JSONDecodeError) as exc:
        logging.error("Generation error: %s", exc)
        raise HTTPException(502, detail="Upstream AI failed")

    # --------------------------------------------------------------------
    # 4. Enrich report: recent payments + validation of mandatory fields
    # --------------------------------------------------------------------
    try:
        report["recent_payments"] = calculate_recent_payments_by_lender(report.get("account_details", []), months_back=1)
        _validate_user_details(report.get("user_details", {}))
    except ValidationError as exc:
        raise HTTPException(422, detail=str(exc))

    # --------------------------------------------------------------------
    # 5. Persist to database (via *DataPersister*)
    # --------------------------------------------------------------------
    try:
        data_values = _extract_data_values(report)
        persister.save_json_report(data_values=data_values)
    except Exception as exc:
        logging.error("Failed to persist report data: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save report data.")

    if file:
        try:
            extension = file.filename.split(".")[-1]
            file_name = generate_file_name(pan=report["user_details"]["pan"], unique_id=user_id, extension=extension)

            # Read once and pass wrapped stream
            upload_bytes = await file.read()  # <== CORRECT way to read async UploadFile
            file_stream = BytesIO(upload_bytes)
            persister.upload_pdf(file_object=file_stream, report_id=file_name)
            logging.info("PDF file uploaded as %s", file_name)
        except Exception as exc:
            logging.error("Failed to upload file to S3: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to upload PDF file.")

    logging.info("Report generated successfully for PAN=%s", report["user_details"]["pan"])
    return JSONResponse(content=report, status_code=201)


# ---------------------------------------------------------------------
# Mount sub-app
# ---------------------------------------------------------------------
app.mount("/ai", credit_app)