import json
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.config.settings import settings
from app.services.llm_services import GeminiService, OpenAIAnalyzer
from app.services.database_service import database_service
logger = logging.getLogger(__name__)

# class PropertyPriceRange(BaseModel):
#     min_price: Optional[int] = 0
#     max_price: Optional[int] = 0

class PropertyPriceStructuredResponse(BaseModel):
    magicbricks_url: Optional[str] = None
    magicbricks_price: Optional[str] = None
    nobroker_url: Optional[str] = None
    nobroker_price: Optional[str] = None
    acres99_url: Optional[str] = None
    acres99_price: Optional[str] = None
    housing_url: Optional[str] = None
    housing_price: Optional[str] = None
    google_price: Optional[str] = None


class PropertyPriceService:

    def __init__(self):
        self.gemini_model = settings.GEMINI_SEARCH_MODEL
        self.openai_model = settings.SNIFFER_ROI_OPENAI_MODEL
        self.gemini_service = GeminiService()
        self.openai_analyzer = OpenAIAnalyzer()

    def set_model_response(self, model_response_schema: Optional[BaseModel] = None):
        self.gemini_service.set_model_response(model_response_schema)

    def _load_json_response(self, property_data: str) -> dict:
        """Load the JSON response from the property data"""

        # Clear the Gemini response string -- can be replaced with structured response
        try:
            start_data = property_data.find("```json")
            end_data = property_data.find("}\n```")+5
            property_data = property_data[start_data:end_data]
        except Exception as e:
            logger.error(f"Error loading JSON response: {e}")
            return None

        try:
            property_data = property_data.replace("```json", "").replace("```", "")
            property_data = json.loads(property_data)
        except Exception as e:
            logger.error(f"Error loading JSON response: {e}")
            return None
        return property_data

    def _format_property_details(self, property_details: dict) -> str:
        """Format the property details"""
        try:
            property_details = property_details.get("prices")
            price_dictionray = {
                "nobroker_url": property_details.get("nobroker",{}).get("link",""),
                "nobroker_price": property_details.get("nobroker",{}).get("price",""),
                "magicbricks_url": property_details.get("magicbricks",{}).get("link",""),
                "magicbricks_price": property_details.get("magicbricks",{}).get("price",""),
                "acres99_url": property_details.get("99acres",{}).get("link",""),
                "acres99_price": property_details.get("99acres",{}).get("price",""),
                "housing_url": property_details.get("housing",{}).get("link",""),
                "housing_price": property_details.get("housing",{}).get("price",""),
                # "google_url": property_details.get("google_search",{}).get("link",""),
                "google_price": property_details.get("google_search",{}).get("price","")
            }
        except Exception as e:
            logger.error(f"Error formatting property details: {e}")
            return None
        return price_dictionray

    def find_property_price(
                        self,
                        property_name: str,
                        property_id: Optional[str] = None,
                        property_location: Optional[str] = None, 
                        table_name: Optional[str] = "approved_projects"):

        # GPP -> Gemini Model Call
        try:
            search_prompt = """"1.What is the latest property price of %s, %s on magicbricks, nobroker, 99acres, housing.com.
                2. And what is the latest price of this property based on google search.
                3. Also provide the links of the property on each platform.

                Instructions:  
                - Extract the relevant property price data from each platform individually.
                - If data is missing from a platform, explicitly mark `"price": "Not Found"`.  
                - Always include the link to the source page used.  
                - Ensure values reflect the *most recent available listings for today*.""" % (property_name, property_location)

            # logger.info(f"Final prompt: {search_prompt}")
            # breakpoint()

            response = self.gemini_service.search_google(search_prompt, model=self.gemini_model)

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
                system_message="""You are a property price extraction agent.  
                    Parse the provided property data and return only a structured JSON response.  

                    Requirements:  
                    - Extract the **price range** (min–max) for the property from each source.  
                    - Extract the **URL/link** of the source.  
                    - Do not include any extra text, explanation, or strings outside the JSON.  
                    - If a source has no data, set `"price": null` and `"link": null`.""", 
                prompt=str(search_response), 
                model=self.openai_model, 
                response_format=PropertyPriceStructuredResponse
            )
            structured_response = openai_structured_response["data"]
        except Exception as e:
            logger.error(f"Error extracting structured response: {e}")
            return {"message": "Error extracting structured response", "success": False}

        # try:
        #     # Magicbricks Price
        #     min_magicbricks_price = structured_response.get("magicbricks_price", {}).get("min_price", 0)
        #     max_magicbricks_price = structured_response.get("magicbricks_price", {}).get("max_price", 0)
        #     structured_response["magicbricks_price"] = f"{min_magicbricks_price}-{max_magicbricks_price}"

        #     # Nobroker Price
        #     min_nobroker_price = structured_response.get("nobroker_price", {}).get("min_price", 0)
        #     max_nobroker_price = structured_response.get("nobroker_price", {}).get("max_price", 0)
        #     structured_response["nobroker_price"] = f"{min_nobroker_price}-{max_nobroker_price}"

        #     # Acres99 Price
        #     min_acres99_price = structured_response.get("acres99_price", {}).get("min_price", 0)
        #     max_acres99_price = structured_response.get("acres99_price", {}).get("max_price", 0)
        #     structured_response["acres99_price"] = f"{min_acres99_price}-{max_acres99_price}"

        #     # Housing Price
        #     min_housing_price = structured_response.get("housing_price", {}).get("min_price", 0)
        #     max_housing_price = structured_response.get("housing_price", {}).get("max_price", 0)
        #     structured_response["housing_price"] = f"{min_housing_price}-{max_housing_price}"

        #     # Google Price
        #     min_google_price = structured_response.get("google_price", {}).get("min_price", 0)
        #     max_google_price = structured_response.get("google_price", {}).get("max_price", 0)
        #     structured_response["google_price"] = f"{min_google_price}-{max_google_price}"
        # except Exception as e:
        #     logger.error(f"Error formatting property details: {e}")
        #     return {"message": "Error formatting property details", "success": False}
        
        # GPP -> Saving structured response to the database
        try:
            # Updating the property id and updated at
            structured_response["id"] = property_id
            structured_response["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Saving the structured response to the database
            database_response = database_service.save_unique_data(data=structured_response, table_name=table_name, update_if_exists=True)
            # logger.info(f"✅ Database response: {database_response}")
            return {"message": f"Data scraped & {database_response['status']} - {database_response['message']}", "success": True}
        except Exception as e:
            logger.error(f"Error saving structured response: {e}")
            return {"message": f"Error saving structured response: {e}", "success": False}


property_price_service = PropertyPriceService()
            
