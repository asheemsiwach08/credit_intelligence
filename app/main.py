import json
import logging

from typing import Optional, Dict, Any

from PyPDF2 import PdfReader
from fastapi.responses import JSONResponse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.cibil_intelligence_agent import CibilReportGenerator, DataPersister, load_input, Settings
from app.utils.data_utils import calculate_recent_payments_by_lender
from app.utils.error_handling import PDFReadError, BadURLError, OpenAITimeout, ValidationError
from app.views.cibil_intelligence import _read_upload, _resolve_prompt, _validate_user_details, _extract_data_values

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
app = FastAPI()
origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins,
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

# =============================================================================
# Route handlers
# =============================================================================
@app.post("/generate_cibil_report", response_class=JSONResponse)
async def generate_cibil_report(
        file: Optional[UploadFile] = File(None),
        source_url: Optional[str] = Form(None),
        prompt: Optional[str] = Form(None),
        pdf_password: Optional[str] = Form(None)):
    """Generate a CIBIL intelligence report from either an uploaded file or
    a source URL/raw JSON.

    Exactly one of file or source_url must be supplied; supplying both
    (or neither) yields a 400.
    """
    if bool(file) == bool(source_url):  # validation
        raise HTTPException(400, detail="Provide either file or source_url, but not both.")

    # --------------------------------------------------------------------
    # 1. Obtain raw text (and optional pdf_path) from the provided source
    # --------------------------------------------------------------------
    try:
        if file:
            raw_text, pdf_path = _read_upload(file, pdf_password)
        else:
            raw_text, pdf_path = load_input(source_url, password=pdf_password)
    except (PDFReadError, BadURLError, Exception) as exc:
        raise HTTPException(400, detail=str(exc))
    # --------------------------------------------------------------------
    # 2. Resolve the user‑supplied prompt override
    # --------------------------------------------------------------------
    prompt_override = _resolve_prompt(prompt)

    # --------------------------------------------------------------------
    # 3. Generate the report via OpenAI‑powered *CibilReportGenerator*
    # --------------------------------------------------------------------
    try:
        settings = Settings.load()
        generator = CibilReportGenerator(openai_key=settings.openai_key)
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
    persister = DataPersister(settings=settings)
    data_values = _extract_data_values(report)
    persister.save_json_report(data_values=data_values)
    # Optional: persist PDF if required
    # if pdf_path:
    #     persister.upload_pdf(Path(pdf_path), report_id=report["user_details"]["pan"])

    logging.info("Report generated successfully for PAN=%s", report["user_details"]["pan"])
    return JSONResponse(content=report, status_code=201)
