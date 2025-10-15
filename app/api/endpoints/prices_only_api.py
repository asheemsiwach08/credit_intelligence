# app/routes/prices_only_api.py
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# --- DB (psycopg2) ---
import psycopg2
from psycopg2.extras import dict_row

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["property price"])

# ---------- CONFIG ----------
DATABASE_URL = os.getenv("DATABASE_URL")  # e.g., postgres://user:pass@host:5432/db
ALLOWED_TABLES = {"approved_projects"}    # hard-allowlist for safety

ALLOWED_SOURCES = {"google", "nobroker", "magicbricks", "99acres", "housing"}
SRC_TO_COL = {
    "google":      "google_price",
    "nobroker":    "nobroker_price",
    "magicbricks": "magicbricks_price",
    "99acres":     "acres99_price",
    "housing":     "housing_price",
}

# ---------- Optional: try to use your existing Gemini pipeline if available ----------
USE_GEMINI_PIPELINE = True
_property_price_service = None
if USE_GEMINI_PIPELINE:
    try:
        from app.services.property_price_service import property_price_service as _pps
        _property_price_service = _pps
        logger.info("✅ Using existing property_price_service (Gemini pipeline).")
    except Exception:
        logger.warning("⚠️ property_price_service not found; will require custom price fetcher.")
        _property_price_service = None

# ---------- Models ----------
class PriceOnlyRequest(BaseModel):
    id: Optional[str] = None
    project_name: Optional[str] = None
    city: Optional[str] = None
    table_name: Optional[str] = "approved_projects"
    sources: Optional[List[str]] = None   # subset of ALLOWED_SOURCES

class PriceOnlyResponse(BaseModel):
    status: str
    project_name: str
    updated_columns: List[str]
    message: str

# ---------- DB helpers ----------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, row_factory=dict_row)

def _validate_table(name: str) -> str:
    if name not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid table. Allowed: {sorted(ALLOWED_TABLES)}")
    return name

def _resolve_project_id(table: str, project_name: Optional[str], city: Optional[str]) -> Dict[str, str]:
    if not (project_name and city):
        raise HTTPException(status_code=400, detail="Provide either id OR (project_name and city).")
    sql = f"""
      select id, project_name
      from {table}
      where lower(project_name)=lower(%s) and lower(city)=lower(%s)
      order by updated_at desc nulls last
      limit 1
    """
    with _conn() as con, con.cursor() as cur:
        cur.execute(sql, (project_name, city))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found for given name & city.")
        return {"id": row["id"], "project_name": row["project_name"]}

def _update_prices_row(table: str, row_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update only provided columns by id."""
    cols = list(updates.keys())
    if not cols:
        return {"status": "noop", "message": "No columns to update"}
    set_frag = ", ".join([f"{c}=%s" for c in cols])
    sql = f"update {table} set {set_frag} where id=%s"
    values = [updates[c] for c in cols] + [row_id]
    with _conn() as con, con.cursor() as cur:
        cur.execute(sql, values)
        if cur.rowcount != 1:
            raise HTTPException(status_code=404, detail="Target row not found for update.")
    return {"status": "success", "message": f"Updated {len(cols)} column(s)."}

# ---------- Price fetchers ----------
def _price_text_from(d: Any) -> Optional[str]:
    """Normalize various shapes into a single text like '45 L – 60 L'."""
    if d is None:
        return None
    if isinstance(d, str):
        return d.strip() or None
    if isinstance(d, dict):
        mn = d.get("min")
        mx = d.get("max")
        val = d.get("value")
        if mn and mx:
            return f"{mn} – {mx}"
        return (val or mn or mx)
    return None

def _extract_from_pipeline(project_id: str, project_name: str, city: str, sources: List[str]) -> Dict[str, str]:
    """
    Calls your existing property_price_service (Gemini) if available.
    Returns a dict mapping target DB columns -> text values.
    """
    if not _property_price_service:
        raise HTTPException(status_code=501, detail="Price pipeline not wired in this environment.")

    res = _property_price_service.find_property_price(
        property_id=project_id,
        property_name=project_name or "",
        property_location=city or "",
        new_record=False,
    ) or {}

    data = res.get("data") or {}
    if data.get("property_found") is False:
        raise HTTPException(status_code=404, detail="Scraper/pipeline could not find the property.")

    props = data.get("properties") or []
    p0 = props[0] if props else {}
    prices = p0.get("prices") or {}
    out: Dict[str, str] = {}

    for src in sources:
        text = None
        # structured location first
        if src in prices:
            text = _price_text_from(prices.get(src))
        # fallbacks for flattened keys
        if not text:
            for k in (f"{src}_price", f"{src}_min", f"{src}_max", src):
                if k in p0 and p0[k]:
                    text = str(p0[k])
                    break
        if text:
            out[SRC_TO_COL[src]] = text

    return out

# ---------- Endpoint ----------
@router.post("/property_price/update-prices-only", response_model=PriceOnlyResponse)
def update_prices_only(req: PriceOnlyRequest):
    table = _validate_table(req.table_name or "approved_projects")

    # normalize sources
    srcs = list((set(req.sources or list(ALLOWED_SOURCES))) & ALLOWED_SOURCES)
    if not srcs:
        raise HTTPException(status_code=400, detail=f"sources must be subset of {sorted(ALLOWED_SOURCES)}")

    # resolve target
    if req.id:
        target = {"id": req.id, "project_name": req.project_name or ""}
    else:
        target = _resolve_project_id(table, req.project_name, req.city)

    # fetch prices via pipeline (Gemini) or raise 501 if not wired
    col_values = _extract_from_pipeline(
        project_id=target["id"],
        project_name=target.get("project_name", "") or (req.project_name or ""),
        city=req.city or "",
        sources=srcs,
    )
    if not col_values:
        raise HTTPException(status_code=404, detail="No price data returned by pipeline for requested sources.")

    # timestamps (only refresh these)
    now = datetime.now()
    col_values["last_scraped_at"] = now
    col_values["updated_at"] = now

    # perform partial update
    resp = _update_prices_row(table, target["id"], col_values)
    updated_cols = sorted(col_values.keys())

    return PriceOnlyResponse(
        status="success",
        project_name=target.get("project_name", req.project_name or ""),
        updated_columns=updated_cols,
        message=resp.get("message", "prices updated"),
    )
