# app/api/endpoints/prices_only_api.py
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# DB
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["property price"])

# ----------------------- CONFIG -----------------------
DATABASE_URL = os.getenv("DATABASE_URL")
ALLOWED_TABLES = {"approved_projects"}  # allow-list for safety

ALLOWED_SOURCES = {"google", "nobroker", "magicbricks", "99acres", "housing"}
SRC_TO_COL = {
    "google":      "google_price",
    "nobroker":    "nobroker_price",
    "magicbricks": "magicbricks_price",
    "99acres":     "acres99_price",     # note the schema spelling
    "housing":     "housing_price",
}

# Try to reuse your service (Gemini/OpenAI pipeline)
_property_price_service = None
try:
    from app.services.property_price_service import property_price_service as _pps
    _property_price_service = _pps
    logger.info("✅ Using existing property_price_service (Gemini pipeline).")
except Exception:
    logger.warning("⚠️ property_price_service not found; prices endpoints will return 501 until wired.")

# ----------------------- MODELS -----------------------
class PriceOnlyRequest(BaseModel):
    id: Optional[str] = None
    project_name: Optional[str] = None
    city: Optional[str] = None
    table_name: Optional[str] = "approved_projects"
    sources: Optional[List[str]] = None  # subset of ALLOWED_SOURCES

class PriceOnlyResponse(BaseModel):
    status: str
    project_name: str
    updated_columns: List[str]
    message: str

class BulkPriceUpdateRequest(BaseModel):
    table_name: Optional[str] = "approved_projects"
    sources: Optional[List[str]] = None           # default = all
    cities: Optional[List[str]] = None            # optional filter
    only_stale: bool = True                       # only rows older than interval
    interval_days: int = 1                        # staleness window
    limit: Optional[int] = None                   # cap rows processed
    concurrency: int = 5                          # thread pool size

class BulkItemResult(BaseModel):
    id: str
    project_name: str
    city: Optional[str] = None
    status: str                 # success | not_found | error | no_data
    updated_columns: List[str] = []
    message: str = ""

class BulkPriceUpdateResponse(BaseModel):
    table_name: str
    total_selected: int
    processed: int
    succeeded: int
    failed: int
    results: List[BulkItemResult]

# ----------------------- DB HELPERS -----------------------
def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

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
    with _conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (project_name, city))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found for given name & city.")
        return {"id": row["id"], "project_name": row["project_name"]}

def _select_projects(
    table: str,
    cities: Optional[List[str]],
    only_stale: bool,
    interval_days: int,
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Safely select candidate rows: id, project_name, city.
    - only_stale: updated_at <= now() - interval_days
    - cities: optional IN filter
    - limit: optional LIMIT
    """
    clauses = []
    params: List[Any] = []

    if only_stale:
        clauses.append("updated_at <= (now() - make_interval(days => %s))")
        params.append(int(interval_days))

    if cities:
        # normalize to lowercase
        cities_l = [c.lower() for c in cities if isinstance(c, str)]
        if cities_l:
            clauses.append("lower(city) = ANY(%s)")
            params.append(cities_l)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = "LIMIT %s" if limit and limit > 0 else ""
    if limit and limit > 0:
        params.append(int(limit))

    sql = f"""
      SELECT id, project_name, city
      FROM {table}
      {where_sql}
      ORDER BY updated_at NULLS FIRST, created_at NULLS FIRST
      {limit_sql}
    """.strip()

    with _conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() or []
    return rows

def _update_prices_row(table: str, row_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update only provided columns by id."""
    cols = list(updates.keys())
    if not cols:
        return {"status": "noop", "message": "No columns to update"}
    set_frag = ", ".join([f"{c}=%s" for c in cols])
    sql = f"UPDATE {table} SET {set_frag} WHERE id=%s"
    values = [updates[c] for c in cols] + [row_id]
    with _conn() as con, con.cursor() as cur:
        cur.execute(sql, values)
        if cur.rowcount != 1:
            raise HTTPException(status_code=404, detail="Target row not found for update.")
    return {"status": "success", "message": f"Updated {len(cols)} column(s)."}

# ----------------------- SERVICE EXTRACTION -----------------------
def _extract_from_pipeline(project_id: str, project_name: str, city: str, sources: List[str]) -> Dict[str, str]:
    """
    Calls your property_price_service and maps its top-level *_price keys:
      magicbricks_price, nobroker_price, acres99_price, housing_price, google_price
    -> DB columns via SRC_TO_COL. Ignores URLs deliberately.
    """
    if not _property_price_service:
        raise HTTPException(status_code=501, detail="Price pipeline not wired in this environment.")

    res = _property_price_service.find_property_price(
        property_name=project_name or "",
        new_record=False,
        property_id=project_id,
        property_location=city or "",
    ) or {}

    data = res.get("data") or {}

    # Respect explicit "not found"
    if isinstance(data, dict) and data.get("property_found") is False:
        raise HTTPException(status_code=404, detail="Property not found by pipeline.")

    # Update path: your service returns a flat dict with *_price keys
    flat: Dict[str, Any]
    if "properties" in data and isinstance(data["properties"], list) and data["properties"]:
        flat = data["properties"][0] or {}
    else:
        flat = data

    service_key_for_src = {
        "google":      "google_price",
        "nobroker":    "nobroker_price",
        "magicbricks": "magicbricks_price",
        "99acres":     "acres99_price",
        "housing":     "housing_price",
    }

    out: Dict[str, str] = {}
    for src in sources:
        src_key = service_key_for_src[src]
        val = flat.get(src_key)
        if val:
            out[SRC_TO_COL[src]] = str(val).strip()
            continue
        # Gentle fallback for possible min/max/value keys
        base = "acres99" if src == "99acres" else src_key.replace("_price", "")
        mn = flat.get(f"{base}_min")
        mx = flat.get(f"{base}_max")
        val2 = flat.get(f"{base}_value")
        if mn and mx:
            out[SRC_TO_COL[src]] = f"{mn} – {mx}"
        elif mn or mx or val2:
            out[SRC_TO_COL[src]] = str(val2 or mn or mx)

    return out

# ----------------------- SINGLE ENDPOINT -----------------------
@router.post("/property_price/update-prices-only", response_model=PriceOnlyResponse)
def update_prices_only(req: PriceOnlyRequest):
    table = _validate_table(req.table_name or "approved_projects")

    srcs = list((set(req.sources or list(ALLOWED_SOURCES))) & ALLOWED_SOURCES)
    if not srcs:
        raise HTTPException(status_code=400, detail=f"sources must be subset of {sorted(ALLOWED_SOURCES)}")

    if req.id:
        target = {"id": req.id, "project_name": req.project_name or ""}
        # optional sanity: fetch project_name if missing
        if not target["project_name"]:
            with _conn() as con, con.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT project_name FROM {table} WHERE id=%s", (req.id,))
                r = cur.fetchone()
                target["project_name"] = r["project_name"] if r else ""
    else:
        target = _resolve_project_id(table, req.project_name, req.city)

    # fetch from pipeline
    col_values = _extract_from_pipeline(
        project_id=target["id"],
        project_name=target.get("project_name", "") or (req.project_name or ""),
        city=req.city or "",
        sources=srcs,
    )
    if not col_values:
        raise HTTPException(status_code=404, detail="No price data returned by pipeline for requested sources.")

    now = datetime.now()
    col_values["last_scraped_at"] = now
    col_values["updated_at"] = now

    resp = _update_prices_row(table, target["id"], col_values)
    updated_cols = sorted(col_values.keys())

    return PriceOnlyResponse(
        status="success",
        project_name=target.get("project_name", req.project_name or ""),
        updated_columns=updated_cols,
        message=resp.get("message", "prices updated"),
    )

# ----------------------- BULK ENDPOINT -----------------------
from concurrent.futures import ThreadPoolExecutor, as_completed

@router.post("/property_prices/update-prices-only-bulk", response_model=BulkPriceUpdateResponse)
def update_prices_only_bulk(req: BulkPriceUpdateRequest):
    table = _validate_table(req.table_name or "approved_projects")
    srcs = list((set(req.sources or list(ALLOWED_SOURCES))) & ALLOWED_SOURCES)
    if not srcs:
        raise HTTPException(status_code=400, detail=f"sources must be subset of {sorted(ALLOWED_SOURCES)}")

    # select candidates
    rows = _select_projects(
        table=table,
        cities=req.cities,
        only_stale=req.only_stale,
        interval_days=req.interval_days,
        limit=req.limit,
    )

    total = len(rows)
    if total == 0:
        return BulkPriceUpdateResponse(
            table_name=table, total_selected=0, processed=0, succeeded=0, failed=0, results=[]
        )

    results: List[BulkItemResult] = []

    def _process_one(row: Dict[str, Any]) -> BulkItemResult:
        pid = row["id"]; pname = row.get("project_name", ""); pcity = row.get("city", "")
        try:
            col_values = _extract_from_pipeline(
                project_id=pid, project_name=pname, city=pcity, sources=srcs
            )
            if not col_values:
                return BulkItemResult(id=pid, project_name=pname, city=pcity,
                                      status="no_data", updated_columns=[], message="No price data")
            now = datetime.now()
            col_values["last_scraped_at"] = now
            col_values["updated_at"] = now
            resp = _update_prices_row(table, pid, col_values)
            updated = sorted(col_values.keys())
            return BulkItemResult(
                id=pid, project_name=pname, city=pcity,
                status="success", updated_columns=updated, message=resp.get("message","")
            )
        except HTTPException as he:
            st = "not_found" if he.status_code in (404,) else "error"
            return BulkItemResult(id=pid, project_name=pname, city=pcity, status=st, updated_columns=[], message=str(he.detail))
        except Exception as e:
            return BulkItemResult(id=pid, project_name=pname, city=pcity, status="error", updated_columns=[], message=str(e))

    # concurrency
    processed = 0
    succeeded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, req.concurrency)) as ex:
        futs = [ex.submit(_process_one, r) for r in rows]
        for f in as_completed(futs):
            res = f.result()
            results.append(res)
            processed += 1
            if res.status == "success":
                succeeded += 1
            else:
                failed += 1

    return BulkPriceUpdateResponse(
        table_name=table,
        total_selected=total,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
