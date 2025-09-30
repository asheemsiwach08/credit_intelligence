import uuid
import logging
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from rapidfuzz import process, fuzz

from app.config.settings import settings
from app.services.llm_services import GeminiService, OpenAIAnalyzer
from app.services.database_service import database_service
logger = logging.getLogger(__name__)

class PropertyPriceStructuredResponse(BaseModel):
    # property_found: bool = Field(description="Whether the correctproperty details are found in the data or not")
    project_name: Optional[str] = Field(None,description="The unique name of the property or project user is searching for")
    city: Optional[str] = Field(None,description="The city of the property or project user is searching for")
    property_type: Optional[str] = Field(None,description="The type of the property or project user is searching for i.e Appartment, Flat, Plot, etc.")
    builder_name: Optional[str] = Field(None,description="The name of the builder/developer of the property or project user is searching for")
    magicbricks_url: Optional[str] = None
    magicbricks_price: Optional[str] = None
    nobroker_url: Optional[str] = None
    nobroker_price: Optional[str] = None
    acres99_url: Optional[str] = None
    acres99_price: Optional[str] = None
    housing_url: Optional[str] = None
    housing_price: Optional[str] = None
    google_price: Optional[str] = None
    lenders: List[str] = Field(description="The list of lenders/banks who are providing home loan for the property")

class PropertyPriceStructuredResponseList(BaseModel):
    property_found: bool = Field(description="Whether the correctproperty details are found in the data or not")
    properties: List[PropertyPriceStructuredResponse] = Field(description="The list of properties with the same name")

class PropertyPriceService:

    def __init__(self):
        """Initializing the Property Price Service"""
        self.gemini_model = settings.GEMINI_SEARCH_MODEL
        self.openai_model = settings.SNIFFER_ROI_OPENAI_MODEL
        self.gemini_service = GeminiService()
        self.openai_analyzer = OpenAIAnalyzer()

    def set_model_response(self, model_response_schema: Optional[BaseModel] = None):
        """Setting the model response schema"""
        self.gemini_service.set_model_response(model_response_schema)

    def fuzzy_find(self,query: str, choices, limit=5, score_cutoff=70):
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
                # print("Fuzzy Find Response: ",response[0][0],"....|||")
                if response:
                    similar_lenders.append(response[0][0])
                else:
                    logger.error(f"❌ Not able to find similar lenders for the provided lenders")
            return list(set(similar_lenders))
        except Exception as e:
            logger.error(f"❌ Error finding similar lenders for the provided lenders: {e}")


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

    
    def find_property_price(
                        self,
                        property_name: str,
                        property_id: Optional[str] = None,
                        property_location: Optional[str] = None):
        """Finding the property price based on the property name and location"""

        db_lenders_data = self.fetch_all_lenders()
        db_lenders_list = [lender.get("lender_name") for lender in db_lenders_data]


        # GPP -> Gemini Model Call
        try:
            search_prompt = """"1.What is the latest property price of %s, %s on magicbricks, nobroker, 99acres, housing.com.
                2. And what is the latest price of this property based on google search.
                3. What are the lenders who are actually providing pre-approved loan on this property(not factual).
                4. Also provide the links of the property on each platform.
                5. You can also provide the builder name of the property or project user is searching for.

                Instructions:
                - If there are mutliple properties with same name then return the details of all the properties.  
                - Extract the relevant property price data from each platform individually.
                - If data is missing from a platform, explicitly mark `"price": "Not Found"`.  
                - Always include the link to the source page used. 
                - Check if lenders names are from lenders/banks list, if not then return `"lenders": []`.  
                - Ensure values reflect the *most recent available listings for today*.""" % (property_name, property_location)

            response = self.gemini_service.search_google(search_prompt, model=self.gemini_model)
            # print("Gemini Response: ",response,"....|||")

            if not response.get("success"):
                logger.error(f"Error getting property price: {response.get('error')}")
                return {"message": response.get('error'), "success": False}
            else:
                search_response = response.get("data")

        except Exception as e:
            logger.error(f"Error getting property price: {e}")
            return {"message": "Error getting property price", "success": False}

        # GPP -> OpenAI Structured Response
        try:
            openai_structured_response = self.openai_analyzer.get_structured_response(
                system_message=f"""You are a property price extraction agent.  
                    1. Parse the provided property data and return only a structured JSON response.
                    2. Match the data with %s, %s if the data and the property details are not matching then return `"property_found": false`.
                    3. Check if lenders names are from lenders/banks list - %s, if not then return `"lenders": [].  
                    4. Ensure values reflect the *most recent available listings for today*.
                    5. If property name is same then club the details rather than returning multiple properties.

                    Requirements:  
                    - Check if the data contains the valid property details, if not then return `"property": null`.
                    - Extract the **price range** (min–max) for the property from each source.  
                    - Extract the **URL/link** of the source.  
                    - Do not include any extra text, explanation, or strings outside the JSON.  
                    - If a source has no data, set `"price": null` and `"link": null`.""" % (property_name, property_location, db_lenders_list),
                prompt=str(search_response), 
                model=self.openai_model, 
                response_format=PropertyPriceStructuredResponseList
            )
            structured_response = openai_structured_response["data"]
            
            try:
                if structured_response and "properties" in structured_response:
                    for property in structured_response["properties"]:
                        property["id"] = str(uuid.uuid4())  # generating unique UUID for each property
                        # logger.info(f"Generated UUID {property['id']} for property: {property.get('project_name', 'Unknown')}")
            except Exception as e:
                logger.error(f"Error updating the property id in the structured response: {e}")

                # structured_response["id"] = property_id       # updating the property id in the structured response
            # print("OpenAI Response: ",structured_response,"....|||")
            
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
        # Fetch lenders data
        if new_record:   # fetch lenders data only if the record is new
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

        # Fetch data for Approved Projects Table
        if new_record:
            try:
                approved_projects_data = []
                for property in data_to_update.get("properties"):
                    # Create a copy to avoid modifying the original data
                    property_copy = property.copy()
                    # Remove lenders (exists in PropertyPriceStructuredResponse)
                    property_copy.pop("lenders", None)  # Use None as default to avoid KeyError
                    property_copy["source"] = "Gemini"
                    property_copy["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    property_copy["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    approved_projects_data.append(property_copy)
                data_to_save["approved_projects"] = approved_projects_data
            except Exception as e:
                logger.error(f"Error generating data to save for approved_projects: {e}")
                data_to_save["approved_projects"] = {}
   
        else:
            data_to_save["approved_projects"] = {}
            data_to_save["approved_projects_lenders"] = {}

        # logger.info(f"Data to save: {data_to_save}")
        logger.info(f"✅ Data generated successfully")

        return data_to_save

            
    def updating_records_to_db(self, data_to_save: dict, new_record: bool):

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

        try:
            successfull_records = 0
            failed_records = 0
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
            return {"message": f"Failed to save Approved Projects Lenders Table: {e}", "success": False, "successfull_records": 0, "failed_records": 0}
        
        # Return success response after all operations
        return {"message": f"Data saved to the database successfully", "success": True, "successfull_records": successfull_records, "failed_records": failed_records}


property_price_service = PropertyPriceService()
            
