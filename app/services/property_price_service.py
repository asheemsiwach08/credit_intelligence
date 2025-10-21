import uuid
import logging
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config.settings import settings
from app.services.llm_services import GeminiService, OpenAIAnalyzer
from app.services.database_service import database_service
logger = logging.getLogger(__name__)

class PropertyPriceStructuredResponse(BaseModel):
    # property_found: bool = Field(description="Whether the correctproperty details are found in the data or not")
    project_name: Optional[str] = Field(None,description="The unique name of the property or project user is searching for")
    # property_type: Optional[str] = Field(None,description="The type of the property or project user is searching for i.e Appartment, Flat, Plot, etc.")
    builder_name: Optional[str] = Field(None,description="The name of the builder/developer of the property or project user is searching for")
    lenders: List[str] = Field(description="The list of lenders/banks who are providing home loan for the property")
    city: Optional[str] = Field(None,description="The city of the property or project user is searching for")
    approval_status: Optional[str] = Field(None, description="The approved project finance status of the property or project user is searching for (Approved/Not Approved)")
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
    property_found: bool = Field(description="Whether the correctproperty details are found in the data or not")
    project_name: Optional[str] = Field(None,description="The unique name of the property or project user is searching for")
    # property_type: Optional[str] = Field(None,description="The type of the property or project user is searching for i.e Appartment, Flat, Plot, etc.")
    builder_name: Optional[str] = Field(None,description="The name of the builder/developer of the property or project user is searching for")
    lenders: List[str] = Field(description="The list of lenders/banks who are providing home loan for the property")
    city: Optional[str] = Field(None,description="The city of the property or project user is searching for")
    approval_status: Optional[str] = Field(None, description="The approved project finance status of the property or project user is searching for (Approved/Not Approved)")
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
    property_found: bool = Field(description="Whether the correctproperty details are found in the data or not")
    properties: List[PropertyPriceStructuredResponse] = Field(description="The list of properties which are similar to the user query")

class PropertyPriceService:

    def __init__(self):
        """Initializing the Property Price Service"""
        
        # Models
        # self.gemini_model = settings.GEMINI_SEARCH_MODEL
        self.gemini_single_search_model = settings.GEMINI_SINGLE_SEARCH_MODEL
        self.gemini_multi_search_model = settings.GEMINI_MULTI_SEARCH_MODEL 
        self.openai_model = settings.SNIFFER_ROI_OPENAI_MODEL

        # Services
        self.gemini_service = GeminiService()
        self.openai_analyzer = OpenAIAnalyzer()

    def capitalize_dict_strings(self, data: dict) -> dict:
        """Capitalize all string values in a dictionary"""
        # return {k: v.capitalize() if isinstance(v, str) else v for k, v in data.items()}
        for k, v in data.items():
            if isinstance(v, str) and not v.startswith("http") and k != "id":
                data[k] = v.capitalize()
        return data

    def title_dict_strings(self, data: dict) -> dict:
        """Make Title of all string values in a dictionary"""
        for k, v in data.items():
            if isinstance(v, str) and not v.startswith("http") and k != "id":
                data[k] = v.title()
        return data
        # return {k: v.title() if isinstance(v, str) else v for k, v in data.items()}

    def set_model_response(self, model_response_schema: Optional[BaseModel] = None):
        """Setting the model response schema"""
        self.gemini_service.set_model_response(model_response_schema)

    def fuzzy_find(self,query: str, choices, limit=5, score_cutoff=60):
        """
        Returns top matches with scores (0-100). score_cutoff filters weak matches.
        """
        # WRatio balances partial/typo/token order cases
        return process.extract(
            query, choices, scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
        )

    def find_similar_lenders(self, lenders_list: List[str], system_lenders_list: List[str]) -> List[str]:
        """Finding the similar lenders based on the fuzzy matching of the lenders names from the system lenders list"""
        similar_lenders = []

        try:
            for lender in lenders_list:
                response = self.fuzzy_find(lender, system_lenders_list)
                if response and len(response) > 0 and len(response[0]) > 0:
                    matched_lender = response[0][0]  # Get the best match
                    # print("Fuzzy Find Response: ", matched_lender, "....|||")
                    similar_lenders.append(matched_lender)
                else:
                    logger.warning(f"❌ No similar lender found for: {lender}")
            return list(set(similar_lenders))
        except Exception as e:
            logger.error(f"❌ Error finding similar lenders for the provided lenders: {e}")
            return []


    def fetch_all_lenders(self) -> List[str]:
        """Fetching all the lenders from the lenders table in the database"""
        try:
            response = database_service.run_sql(query=f"select id, lender_name from lenders")
            if response["status"] == "success":
                return response["data"]
            else:
                logger.error(f"❌ Not able to fetch all lenders from the database")
                return []
        except Exception as e:
            logger.error(f"❌ Error fetching all lenders from the database: {e}")
            return []

    def gemini_combined_search_query(self, property_name: str, property_location: str, search_type: str = "single") -> dict:
        """Execute combined Gemini searches for property price data"""

        BASE_SEARCH_QUERIES = {
            "magicbricks": (
                "what is the latest price for {property}, {location} or similar properties on magicbricks, "
                "just share the price range and nothing else - no details, only property name and amounts"
            ),
            "nobroker": (
                "what is the latest price for {property}, {location} or similar properties on nobroker, "
                "just share the price range and nothing else - no details, only property name and amounts"
            ),
            "99acres": (
                "what is the latest price for {property}, {location} or similar properties on 99acres, "
                "just share the price range and nothing else - no details, only property name and amounts"
            ),
            "housing": (
                "what is the latest price for {property}, {location} or similar properties on housing.com, "
                "just share the price range and nothing else - no details, only property name and amounts"
            ),
            "google": (
                "what is the latest price for {property}, {location} or similar properties on google, "
                "just share the price range and nothing else - no details, only property name and amounts"
            ),
            "apf": (
                "what is the approved project finance status of {property}, {location} "
                "just share the status, and lenders nothing else - no other details"
            ),
            "lenders": (
                "what are the lenders/banks who are providing pre-approved loan on {property}, {location} "
                "property(not factual).Provide full name of the lender/bank."
            ),
        }

        prop, loc = property_name, property_location
        combined_search_query = "\n".join(
            f"{i}. {tmpl.format(property=prop, location=loc)}"
            for i, tmpl in enumerate(BASE_SEARCH_QUERIES.values(), 1)
        )
        
        # Try primary model first, then fallback to alternative model
        try:
            logger.info(f"🔄 Attempting search with primary model: {gemini_model}")

            if search_type == "single":
                gemini_model = self.gemini_single_search_model
                result = self.gemini_service.search_google(combined_search_query, model=gemini_model)
            elif search_type == "multi":
                gemini_model = self.gemini_multi_search_model
                result = self.gemini_service.search_google_multi(combined_search_query, model=gemini_model)

            logger.info(f"✅ Search successful with primary model: {gemini_model}")
            return result
            
        except Exception as e:
            logger.warning(f"❌ Primary model {gemini_model} failed: {e}")
            
            # Determine fallback model
            if gemini_model == self.gemini_single_search_model:
                fallback_model = self.gemini_multi_search_model
                logger.info(f"🔄 Switching from single to multi model: {fallback_model}")
            elif gemini_model == self.gemini_multi_search_model:
                fallback_model = self.gemini_single_search_model
                logger.info(f"🔄 Switching from multi to single model: {fallback_model}")
            else:
                # If using auto/fallback model, try the single model as backup
                fallback_model = self.gemini_single_search_model
                logger.info(f"🔄 Using single model as fallback: {fallback_model}")
            
            try:
                logger.info(f"🔄 Attempting search with fallback model: {fallback_model}")
                result = self.gemini_service.search_google_multi(combined_search_query, model=fallback_model)
                logger.info(f"✅ Search successful with fallback model: {fallback_model}")
                return result
                
            except Exception as fallback_error:
                logger.error(f"❌ Both models failed. Primary: {e}, Fallback: {fallback_error}")
                return {
                    "message": f"Both models failed. Primary ({gemini_model}): {str(e)}, Fallback ({fallback_model}): {str(fallback_error)}", 
                    "success": False,
                    "primary_error": str(e),
                    "fallback_error": str(fallback_error)
                }

    def gemini_search_query(self, property_name: str, property_location: str, search_type: str = "single") -> dict:
        """Execute parallel Gemini searches for property price data"""
        
        # Define all search queries
        queries = {
            'magicbricks': "what is the latest price for %s, %s or similar properties on magicbricks, just share the price range and nothing else - no details, only property name and amounts" % (property_name, property_location),
            'nobroker': "what is the latest price for %s, %s or similar properties on nobroker, just share the price range and nothing else - no details, only property name and amounts" % (property_name, property_location),
            '99acres': "what is the latest price for %s, %s or similar properties on 99acres, just share the price range and nothing else - no details, only property name and amounts" % (property_name, property_location),
            'housing': "what is the latest price for %s, %s or similar properties on housing.com, just share the price range and nothing else - no details, only property name and amounts" % (property_name, property_location),
            'google': "what is the latest price for %s, %s or similar properties on google, just share the price range and nothing else - no details, only property name and amounts" % (property_name, property_location),
            'apf': "what is the approved project finance status of %s, %s just share the status, and lenders nothing else - no other details" % (property_name, property_location),
            'lenders': "what are the lenders/banks who are providing pre-approved loan on %s, %s property(not factual).Provide full name of the lender/bank." % (property_name, property_location)
        }
        
        def search_single_platform(platform_query):
            """Execute a single search query with model fallback"""
            platform, query = platform_query
            
            # Try primary model first
            try:
                if search_type == "single":
                    gemini_model = self.gemini_single_search_model
                    result = self.gemini_service.search_google(query, model=gemini_model)
                elif search_type == "multi":
                    gemini_model = self.gemini_multi_search_model
                    result = self.gemini_service.search_google_multi(query, model=gemini_model)

                logger.info(f"✅ {platform.title()} search completed with primary model: {gemini_model}")
                return platform, result
                
            except Exception as e:
                logger.warning(f"⚠️ {platform.title()} failed with primary model {gemini_model}: {e}")
                
                # Determine fallback model
                if gemini_model == self.gemini_single_search_model:
                    fallback_model = self.gemini_multi_search_model
                elif gemini_model == self.gemini_multi_search_model:
                    fallback_model = self.gemini_single_search_model
                else:
                    fallback_model = self.gemini_single_search_model
                
                # Try fallback model
                try:
                    result = self.gemini_service.search_google_multi(query, model=fallback_model)
                    logger.info(f"✅ {platform.title()} search completed with fallback model: {fallback_model}")
                    return platform, result
                    
                except Exception as fallback_error:
                    logger.error(f"❌ {platform.title()} failed with both models. Primary: {e}, Fallback: {fallback_error}")
                    return platform, {
                        "success": False, 
                        "error": f"Both models failed. Primary: {str(e)}, Fallback: {str(fallback_error)}",
                        "primary_error": str(e),
                        "fallback_error": str(fallback_error)
                    }
        
        # Execute all searches in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all tasks
            future_to_platform = {
                executor.submit(search_single_platform, (platform, query)): platform
                for platform, query in queries.items()
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_platform):
                try:
                    platform, result = future.result()
                    results[platform] = result
                except Exception as e:
                    platform = future_to_platform[future]
                    logger.error(f"❌ Error in {platform} search: {e}")
                    results[platform] = {"success": False, "error": str(e)}
        
        logger.info(f"✅ Parallel search completed for {len(results)} platforms")
        return results

    
    def find_property_price(
                        self,
                        property_name: str,
                        new_record: bool,
                        combined_search: bool = False,
                        search_type: str = "single",
                        property_id: Optional[str] = None,
                        property_location: Optional[str] = None):
        """Finding the property price based on the property name and location"""

        # Fetching all the lenders from the lenders table in the database
        # db_lenders_data = self.fetch_all_lenders()
        # db_lenders_list = [lender.get("lender_name") for lender in db_lenders_data]

        # Setting the model output based on the new record
        if new_record:
            model_output = PropertyPriceStructuredResponseList
        else:
            model_output = SinglePropertyPriceStructuredResponse


        try: 
            if combined_search:
                logger.info(f"🔄 Executing combined Gemini search query")
                search_response = self.gemini_combined_search_query(property_name, property_location, search_type)
            else:
                logger.info(f"🔄 Executing Gemini search query")
                search_response = self.gemini_search_query(property_name, property_location, search_type)

        except Exception as e:
            logger.error(f"Error getting property price: {e}")
            return {"message": "Error getting property price", "success": False}

        # Restructuring the gemini search response for openai structured response
        try:
            search_response_data = ""
            if combined_search:
                search_response_data = search_response.get("data")
            else:
                for platform, result in search_response.items():
                    if result.get("success"):
                        search_response_data += f"{platform.title()}: {result.get('data')}\n"
                search_response_data = search_response_data.strip()
                # print("Search Response Data: ",search_response_data,"....|||")
        except Exception as e:
            logger.error(f"Error restructuring the gemini search response: {e}")
            return {"message": "Error restructuring the gemini search response", "success": False}

        # GPP -> OpenAI Structured Response
        try:
            system_message=f"""You are a property price extraction agent. Follow these rules strictly:
                1. Parse Input: Extract structured property data and return only a valid JSON object as output. No extra text or explanation.
                2. Property Match: Match the parsed data with the given property name and city (%s, %s).
                    If they do not match, return: false in property_found key.

                3. Lenders Validation: Check the lenders names from the user query and return the name in Capitalize. Keep all the lenders names in the list from the user query.
                    If no valid lenders are found, set "lenders": [].
                4. Freshness: Ensure values reflect the most recent available listings for today.
                5. Price Extraction: Extract the price range (min–max) from each source return only numeric prices range.
                    a. Normalize price format: Thousands → K, Lakhs → L, Crores → Cr.
                    b. Do not include values like "Price on request", "Contact for price","From","Starting" etc or any non-numeric ranges.
                    c. If price is missing or invalid, set "price": "".
                6. Extract and include the source URL ("link").
                7. If source has no valid data, set "price": "" and "link": "".
                8. If multiple properties exist in the user query then return the details of all the properties whose name is similar to user query but unique.
                        """ % (property_name, property_location)
            openai_structured_response = self.openai_analyzer.get_structured_response(
                system_message=system_message,
                prompt=str(search_response_data), 
                model=self.openai_model, 
                response_format=model_output
            )
            structured_response = openai_structured_response["data"]
            
            try:
                if new_record:
                    if structured_response and "properties" in structured_response:
                        for property in structured_response["properties"]:
                            property["id"] = str(uuid.uuid4())  # generating unique UUID for each property
                            # logger.info(f"Generated UUID {property['id']} for property: {property.get('project_name', 'Unknown')}")
                else:
                    structured_response["id"] = property_id
            except Exception as e:
                logger.error(f"Error updating the property id in the structured response: {e}")
            
            return {"message": "Error extracting structured response", "success": False, "data":structured_response}
        except Exception as e:
            logger.error(f"Error extracting structured response: {e}")
            return {"message": "Error extracting structured response", "success": False, "data":None}


    def fetch_similar_lenders_from_db(self, data_to_update: dict):

        # GPP -> Find the similar lenders
        if not isinstance(data_to_update.get("lenders"), list) or len(data_to_update.get("lenders")) == 0:
            return {}
        else:
            try:
                # Get all the lenders from the database
                db_lenders_data = self.fetch_all_lenders()
                db_lenders_list = [lender.get("lender_name") for lender in db_lenders_data]

                # GPP -> Find the similar lenders
                similar_lenders = self.find_similar_lenders(data_to_update.get("lenders"), db_lenders_list)
                data_to_update["lenders"] = similar_lenders      # updating the data to update lenders list with the real names
                # print("Similar Lenders: ",similar_lenders,"....|||")

                # Fetching the lenders id of the matched lenders
                data =  {
                        rec['id']: rec['lender_name']
                        for rec in db_lenders_data
                        if rec['lender_name'] in set(similar_lenders)
                    }
                logger.info(f"✅ Similar lenders fetched successfully")
                return data
            except Exception as e:
                logger.info(f"❌  Similar lenders fetching failed")
                return {"message": f"Error finding similar lenders: {e}", "success": False}


    def generate_data_to_save(self, data_to_update: dict, new_record: bool):

        data_to_save = {}  # data to return
        
        # Fetch lenders data only if the record is new
        if new_record: 
            property_plus_lenders = []
            for property in data_to_update.get("properties"):
                fetched_lenders_data = self.fetch_similar_lenders_from_db(property)
                if fetched_lenders_data:
                    fetched_lenders_id = list(fetched_lenders_data.keys())

                    try:
                        logger.info(f"✅ Fetching lenders data for property: {property.get('project_name')}")
                        approved_projects_lenders = []
                        for lender_id in fetched_lenders_id:
                            approved_projects_lenders.append({
                                "project_id": property.get("id"),
                                "lender_id" : lender_id,
                                "created_at" : datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                        property_plus_lenders.append({property.get("project_name"):approved_projects_lenders}) 
                    except Exception as e:
                        logger.info(f"Error generating data to save for approved_projects_lenders: {e}")
                        property_plus_lenders.append({property.get("project_name"):[]})

            data_to_save["approved_projects_lenders"] = property_plus_lenders
        else:
            data_to_save["approved_projects_lenders"] = {}

        # Fetch data for Approved Projects Table
        if new_record:
            try:
                approved_projects_data = []
                for property in data_to_update.get("properties"):
                    property_copy = self.title_dict_strings(property.copy())
                    # Remove lenders (exists in PropertyPriceStructuredResponse)
                    if property_copy.get("lenders"):
                        property_copy["approval_status"] = "Approved"
                    else:
                        property_copy["approval_status"] = "Not Approved"

                    property_copy.pop("lenders", None)  # Use None as default to avoid KeyError
                    property_copy["source"] = "Gemini"
                    property_copy["last_scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    property_copy["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    property_copy["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    approved_projects_data.append(property_copy)
                data_to_save["approved_projects"] = approved_projects_data
            except Exception as e:
                logger.error(f"Error generating data to save for approved_projects: {e}")
                data_to_save["approved_projects"] = {}
   
        else:
            try:
                approved_projects_data = self.title_dict_strings(data_to_update.copy())
                if approved_projects_data.get("lenders"):
                        approved_projects_data["approval_status"] = "Approved"
                else:
                    approved_projects_data["approval_status"] = "Not Approved"
                approved_projects_data.pop("property_found", None)
                approved_projects_data.pop("lenders", None)
                approved_projects_data.pop("project_name", None)
                approved_projects_data.pop("property_type", None)
                approved_projects_data.pop("builder_name", None)
                approved_projects_data.pop("city", None)
                approved_projects_data["source"] = "Gemini"
                approved_projects_data["last_scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                approved_projects_data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                data_to_save["approved_projects"] = approved_projects_data
            except Exception as e:
                logger.error(f"Error generating data to save for approved_projects: {e}")
                data_to_save["approved_projects"] = {}
            

        # logger.info(f"Data to save: {data_to_save}")
        logger.info(f"✅ Data generated successfully")

        return data_to_save

            
    def updating_records_to_db(self, data_to_save: dict, new_record: bool):

        if new_record:
            # GPP -> Saving structured response to the approved_projects table
            try:
                for property in data_to_save.get("approved_projects"):
                    approved_projects_response = database_service.save_unique_data(data=property, table_name="approved_projects", update_if_exists=True)
                    if approved_projects_response:
                        logger.info(f"✅ Approved Projects Table {approved_projects_response['status']} - {approved_projects_response['message']}")
                    else:
                        logger.error(f"❌ Failed to save Approved Projects Table")
            except Exception as e:
                logger.error(f"❌ Failed to save Approved Projects Table: {e}")
        else:
            try:
                approved_projects_response = database_service.save_unique_data(data=data_to_save.get("approved_projects"), table_name="approved_projects", update_if_exists=True)
                if approved_projects_response:
                    logger.info(f"✅ Approved Projects Table {approved_projects_response['status']} - {approved_projects_response['message']}")
                else:
                    logger.error(f"❌ Failed to save Approved Projects Table")
            except Exception as e:
                logger.error(f"❌ Failed to save Approved Projects Table: {e}")

        try:
            successfull_records = 0
            failed_records = 0
            lenders_ids = []
            if new_record:  # save lenders data only if the record is new
                approved_projects_lenders_data = data_to_save.get("approved_projects_lenders")
                logger.info(f"Processing {len(approved_projects_lenders_data)} property groups for lenders data")
                
                for property_data in approved_projects_lenders_data:
                    # property_data is a dict like {"PropertyName": [list_of_lender_records]}
                    for property_name, lender_records in property_data.items():
                        logger.info(f"Processing lenders for property: {property_name}")
                        if len(lender_records) > 0:
                            for lender_record in lender_records:
                                approved_projects_lenders_response = database_service.save_data(data=lender_record, table_name="approved_projects_lenders")
                                if approved_projects_lenders_response:
                                    successfull_records += 1
                                    lenders_ids.append(lender_record.get('lender_id'))
                                    logger.info(f"✅ Saved lender {lender_record.get('lender_id')} for project {lender_record.get('project_id')}")
                                else:
                                    failed_records += 1
                                    logger.error(f"❌ Failed to save lender {lender_record.get('lender_id')} for project {lender_record.get('project_id')}")
                        else:
                            logger.info(f"✅ No lenders to save for property: {property_name}")
                
                logger.info(f"✅ Lenders processing complete - Successful: {successfull_records}, Failed: {failed_records}")
            else:
                logger.info(f"✅ Skipping lenders data - not a new record")
            
        except Exception as e:
            logger.error(f"❌ Failed to save Approved Projects Lenders Table: {e}")
            return {"message": f"Failed to save Approved Projects Lenders Table: {e}", "success": False, "successfull_records": 0, "failed_records": 0, "lenders_ids": []}
        
        # Return success response after all operations
        return {"message": f"Data saved to the database successfully", "success": True, "successfull_records": successfull_records, "failed_records": failed_records, "lenders_id": lenders_ids}


property_price_service = PropertyPriceService()
            
