# app/services/property_price_service.py
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config.settings import settings
from app.services.llm_services import GeminiService, OpenAIAnalyzer
from app.services.database_service import database_service

logger = logging.getLogger(__name__)

# ----------------------------- Pydantic models -----------------------------

class PropertyPriceStructuredResponse(BaseModel):
    project_name: Optional[str] = Field(None, description="The property / project name")
    property_type: Optional[str] = Field(None, description="Apartment, Plot, etc.")
    builder_name: Optional[str] = Field(None, description="Builder / Developer")
    lenders: List[str] = Field(default_factory=list, description="Banks offering loans")
    city: Optional[str] = Field(None, description="City")
    approval_status: Optional[str] = Field(None, description="Approved/Not Approved")
    magicbricks_url: Optional[str] = None
    magicbricks_price: Optional[str] = None
    nobroker_url: Optional[str] = None
    nobroker_price: Optional[str] = None
    acres99_url: Optional[str] = None
    acres99_price: Optional[str] = None
    housing_url: Optional[str] = None
    housing_price: Optional[str] = None
    google_price: Optional[str] = None

class SinglePropertyPriceStructuredResponse(BaseModel):
    property_found: bool = Field(description="Whether the correct property was found")
    project_name: Optional[str] = None
    property_type: Optional[str] = None
    builder_name: Optional[str] = None
    lenders: List[str] = Field(default_factory=list)
    city: Optional[str] = None
    approval_status: Optional[str] = None
    magicbricks_url: Optional[str] = None
    magicbricks_price: Optional[str] = None
    nobroker_url: Optional[str] = None
    nobroker_price: Optional[str] = None
    acres99_url: Optional[str] = None
    acres99_price: Optional[str] = None
    housing_url: Optional[str] = None
    housing_price: Optional[str] = None
    google_price: Optional[str] = None

class PropertyPriceStructuredResponseList(BaseModel):
    property_found: bool = Field(description="Whether matching properties were found overall")
    properties: List[PropertyPriceStructuredResponse] = Field(default_factory=list, description="Similar properties")

# ----------------------------- Service class -----------------------------

class PropertyPriceService:
    def __init__(self):
        self.gemini_model = settings.GEMINI_SEARCH_MODEL
        self.openai_model = settings.SNIFFER_ROI_OPENAI_MODEL
        self.gemini_service = GeminiService()
        self.openai_analyzer = OpenAIAnalyzer()

    # ---------- string normalizers ----------
    def capitalize_dict_strings(self, data: dict) -> dict:
        for k, v in data.items():
            if isinstance(v, str) and not v.startswith("http") and k != "id":
                data[k] = v.capitalize()
        return data

    def title_dict_strings(self, data: dict) -> dict:
        for k, v in data.items():
            if isinstance(v, str) and not v.startswith("http") and k != "id":
                data[k] = v.title()
        return data

    # ---------- search + fuzzy ----------
    def set_model_response(self, model_response_schema: Optional[BaseModel] = None):
        self.gemini_service.set_model_response(model_response_schema)

    def fuzzy_find(self, query: str, choices, limit=5, score_cutoff=60):
        return process.extract(query, choices, scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff)

    def find_similar_lenders(self, lenders_list: List[str], system_lenders_list: List[str]) -> List[str]:
        similar_lenders: List[str] = []
        try:
            for lender in lenders_list or []:
                response = self.fuzzy_find(lender, system_lenders_list)
                if response and response[0]:
                    matched = response[0][0]
                    similar_lenders.append(matched)
                else:
                    logger.warning(f"❌ No similar lender found for: {lender}")
            return list(set(similar_lenders))
        except Exception as e:
            logger.error(f"❌ Error in lender similarity: {e}")
            return []

    def fetch_all_lenders(self) -> List[Dict[str, Any]]:
        try:
            resp = database_service.run_sql("select id, lender_name from lenders")
            if resp.get("status") == "success":
                return resp.get("data", [])
            logger.error("❌ Could not fetch lenders")
            return []
        except Exception as e:
            logger.error(f"❌ DB error fetching lenders: {e}")
            return []

    # ---------- Gemini parallel search ----------
    def gemini_search_query(self, property_name: str, property_location: Optional[str]) -> dict:
        pn, pl = (property_name or "").strip(), (property_location or "").strip()
        queries = {
            "magicbricks": f"what is the latest price for {pn}, {pl} or similar properties on magicbricks, share only the price range",
            "nobroker":    f"what is the latest price for {pn}, {pl} or similar properties on nobroker, share only the price range",
            "99acres":     f"what is the latest price for {pn}, {pl} or similar properties on 99acres, share only the price range",
            "housing":     f"what is the latest price for {pn}, {pl} or similar properties on housing.com, share only the price range",
            "google":      f"what is the latest price for {pn}, {pl} or similar properties on google, share only the price range",
            "apf":         f"what is the approved project finance status of {pn}, {pl} just the status and lenders",
            "lenders":     f"what are the lenders/banks providing pre-approved loan on {pn}, {pl} (not factual). Provide full names.",
        }

        def one(qitem):
            platform, q = qitem
            try:
                res = self.gemini_service.search_google(q, model=self.gemini_model)
                logger.info(f"✅ {platform.title()} search completed")
                return platform, res
            except Exception as e:
                logger.error(f"❌ {platform.title()} search failed: {e}")
                return platform, {"success": False, "error": str(e)}

        results: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            fut = {ex.submit(one, (k, v)): k for k, v in queries.items()}
            for f in as_completed(fut):
                try:
                    platform, result = f.result()
                    results[platform] = result
                except Exception as e:
                    platform = fut[f]
                    logger.error(f"❌ Error collecting {platform} search: {e}")
                    results[platform] = {"success": False, "error": str(e)}
        logger.info(f"✅ Parallel search completed for {len(results)} platforms")
        return results

    # ---------- main: find_property_price ----------
    def find_property_price(
        self,
        property_name: str,
        new_record: bool,
        property_id: Optional[str] = None,
        property_location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        new_record = True  -> returns PropertyPriceStructuredResponseList (properties[])
        new_record = False -> returns SinglePropertyPriceStructuredResponse (flat dict)
                              with *_price keys at the top level (for prices-only update)
        """
        # 1) Fetch lenders upfront
        db_lenders_data = self.fetch_all_lenders()
        db_lenders_list = [x.get("lender_name") for x in db_lenders_data]

        # 2) Choose response schema
        model_output = PropertyPriceStructuredResponseList if new_record else SinglePropertyPriceStructuredResponse

        # 3) Do parallel Gemini queries
        try:
            search_response = self.gemini_search_query(property_name, property_location)
        except Exception as e:
            logger.error(f"❌ Gemini search error: {e}")
            return {"message": "Gemini search failed", "success": False, "data": None}

        # 4) Flatten the search results into a single plain prompt for OpenAI
        try:
            buf = []
            for platform, result in search_response.items():
                if isinstance(result, dict) and result.get("success"):
                    buf.append(f"{platform.title()}: {result.get('data')}")
            search_response_data = "\n".join(buf).strip()
        except Exception as e:
            logger.error(f"❌ Error restructuring Gemini results: {e}")
            return {"message": "Aggregation error", "success": False, "data": None}

        # 5) Ask OpenAI for structured output
        try:
            system_message = (
                "You are a property price extraction agent. Rules:\n"
                f"1) Parse and return ONLY valid JSON per schema. No extra text.\n"
                f"2) Match property and city: {property_name}, {property_location}. "
                f"If not matching, set property_found=false.\n"
                "3) Lenders: capitalize names; if none valid, lenders=[].\n"
                "4) Freshness: values should be the most recent for today.\n"
                "5) Price: extract numeric min–max only; normalize K/L/Cr; "
                'reject phrases like "Price on request"; if missing -> "".\n'
                "6) Include source URL if present; else empty string.\n"
                "7) If multiple similar properties, include unique ones.\n"
            )
            # self.set_model_response(model_output)
            openai_structured = self.openai_analyzer.get_structured_response(
                system_message=system_message,
                prompt=search_response_data,
                model=self.openai_model,
                response_format=model_output,
            )
            structured = openai_structured.get("data")

            # id handling
            if new_record:
                if structured and isinstance(structured, dict) and "properties" in structured:
                    for prop in structured.get("properties", []):
                        prop["id"] = str(uuid.uuid4())
            else:
                if isinstance(structured, dict) and property_id:
                    structured["id"] = property_id

            return {"message": "OK", "success": True, "data": structured}

        except Exception as e:
            logger.error(f"❌ OpenAI structuring error: {e}")
            return {"message": "Structuring failed", "success": False, "data": None}

    # ---------- lenders helper ----------
    def fetch_similar_lenders_from_db(self, data_to_update: dict) -> Dict[str, str]:
        lenders = data_to_update.get("lenders")
        if not isinstance(lenders, list) or not lenders:
            return {}
        try:
            all_lenders = self.fetch_all_lenders()
            names = [x.get("lender_name") for x in all_lenders]
            similar = self.find_similar_lenders(lenders, names)
            data_to_update["lenders"] = similar
            mapping = {rec["id"]: rec["lender_name"] for rec in all_lenders if rec["lender_name"] in set(similar)}
            logger.info("✅ Similar lenders fetched")
            return mapping
        except Exception as e:
            logger.warning(f"❌ Similar lenders fetch failed: {e}")
            return {}

    # ---------- save payload builder ----------
    def generate_data_to_save(self, data_to_update: dict, new_record: bool) -> Dict[str, Any]:
        data_to_save: Dict[str, Any] = {}

        # approved_projects_lenders (only on insert)
        if new_record:
            property_plus_lenders: List[Dict[str, Any]] = []
            for prop in data_to_update.get("properties", []):
                matched = self.fetch_similar_lenders_from_db(prop)
                if matched:
                    ids = list(matched.keys())
                    try:
                        logger.info(f"✅ Linking lenders for: {prop.get('project_name')}")
                        rows = [
                            {"project_id": prop.get("id"), "lender_id": lid, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            for lid in ids
                        ]
                        property_plus_lenders.append({prop.get("project_name"): rows})
                    except Exception as e:
                        logger.info(f"❌ Error creating lender rows: {e}")
                        property_plus_lenders.append({prop.get("project_name"): []})
                else:
                    property_plus_lenders.append({prop.get("project_name"): []})
            data_to_save["approved_projects_lenders"] = property_plus_lenders
        else:
            data_to_save["approved_projects_lenders"] = {}

        # approved_projects payload
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if new_record:
            try:
                approved_list: List[Dict[str, Any]] = []
                for prop in data_to_update.get("properties", []):
                    tmp = self.title_dict_strings(prop.copy())
                    tmp["approval_status"] = "Approved" if tmp.get("lenders") else "Not Approved"
                    tmp.pop("lenders", None)
                    tmp["source"] = "Gemini"
                    tmp["last_scraped_at"] = now_str
                    tmp["created_at"] = now_str
                    tmp["updated_at"] = now_str
                    approved_list.append(tmp)
                data_to_save["approved_projects"] = approved_list
            except Exception as e:
                logger.error(f"❌ Error building approved_projects (insert): {e}")
                data_to_save["approved_projects"] = {}
        else:
            try:
                upd = self.title_dict_strings((data_to_update or {}).copy())
                upd["approval_status"] = "Approved" if upd.get("lenders") else "Not Approved"
                # Do not change identity fields on updates
                for k in ["property_found", "lenders", "project_name", "property_type", "builder_name", "city"]:
                    upd.pop(k, None)
                upd["source"] = "Gemini"
                upd["last_scraped_at"] = now_str
                upd["updated_at"] = now_str
                data_to_save["approved_projects"] = upd
            except Exception as e:
                logger.error(f"❌ Error building approved_projects (update): {e}")
                data_to_save["approved_projects"] = {}

        logger.info("✅ Data generated successfully")
        return data_to_save

    # ---------- DB write ----------
    def updating_records_to_db(self, data_to_save: dict, new_record: bool) -> Dict[str, Any]:
        try:
            if new_record:
                for prop in data_to_save.get("approved_projects", []):
                    resp = database_service.save_unique_data(
                        data=prop, table_name="approved_projects", update_if_exists=True
                    )
                    if resp:
                        logger.info(f"✅ Approved Projects {resp['status']} - {resp['message']}")
                    else:
                        logger.error("❌ Failed to save Approved Projects row")
            else:
                resp = database_service.save_unique_data(
                    data=data_to_save.get("approved_projects"),
                    table_name="approved_projects",
                    update_if_exists=True,
                )
                if resp:
                    logger.info(f"✅ Approved Projects {resp['status']} - {resp['message']}")
                else:
                    logger.error("❌ Failed to save Approved Projects")
        except Exception as e:
            logger.error(f"❌ Approved Projects write error: {e}")

        # lenders link table on insert
        success = 0
        fail = 0
        try:
            if new_record:
                groups = data_to_save.get("approved_projects_lenders", [])
                logger.info(f"Linking lenders for {len(groups)} properties")
                for grp in groups:
                    for pname, rows in grp.items():
                        if rows:
                            for r in rows:
                                resp = database_service.save_data(data=r, table_name="approved_projects_lenders")
                                if resp:
                                    success += 1
                                else:
                                    fail += 1
                        else:
                            logger.info(f"ℹ️ No lenders for: {pname}")
                logger.info(f"✅ Lenders linking complete - ok:{success}, fail:{fail}")
            else:
                logger.info("⏭️ Skipping lenders linking (update path)")
        except Exception as e:
            logger.error(f"❌ Lenders write error: {e}")
            return {"message": f"Lenders write failed: {e}", "success": False, "successfull_records": 0, "failed_records": 0}

        return {"message": "Data saved to the database successfully", "success": True, "successfull_records": success, "failed_records": fail}


property_price_service = PropertyPriceService()
