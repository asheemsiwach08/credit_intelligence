import uuid
import logging
from typing import Optional
from datetime import datetime, timezone
import pytz

from app.config.settings import settings
from app.services.database_service import database_service
from app.models.schemas import LendersGeminiSearchResponse
from app.services.llm_services import GeminiService, OpenAIAnalyzer
logger = logging.getLogger(__name__)

#################################### Scrape Lenders ROI ####################################

class ScrapeLendersROI:

    def __init__(self):
        self.gemini_model = settings.GEMINI_SEARCH_MODEL
        self.openai_model = settings.SNIFFER_ROI_OPENAI_MODEL
        self.gemini_service = GeminiService()
        self.openai_analyzer = OpenAIAnalyzer()

    def get_lenders_roi(self,
                            lender_name: str, 
                            lender_id: Optional[str] = None, 
                            table_name: Optional[str] = "lenders") -> dict:
        
        #LROI 1:Validation Checks
        if not lender_id:
            logger.info("Lender ID is missing, generating a new one")
            lender_id = str(uuid.uuid4())
        if not lender_name:
            return {"message": "Lender name is required", "status_code": 400}

        #LROI 2:Search Scraper Prompt
        search_scraper_prompt = f"""What is the 
                1. interest rate, 
                2. Loan-to-value, 
                3. minimum credit score, 
                4. loan amount range, 
                5. loan tenure range, 
                6. approval time, 
                7. processing fee, 
                8. special Offers
                for home loan in India for {lender_name} effective from {datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%B, %Y")}."""
        logger.info(f"Searching for {lender_name} ROI from Google")
        # breakpoint()

        #LROI 3.1:Search Google
        try:
            first_tool_response = self.gemini_service.search_google(search_scraper_prompt, model=self.gemini_model)
        except Exception as e:
            logger.error(f"Error searching google: {e}")
            return {"message": "Error searching google", "status_code": 500}

        #LROI 3.2:Check if the search response is not None
        if not first_tool_response:
            logger.error(f"Error searching google: {first_tool_response['error']}")
            return {"message": "Error searching google", "status_code": 500}
        else:
            search_response = first_tool_response["data"]

            #LROI 3.3:Extract the structured response - OPENAI Analyzer
            try:
                openai_structured_response = self.openai_analyzer.get_structured_response(
                    system_message="You are a helpful assistant which can extract the information from the data provided by the user. Parse that data into valuable structured response and provide the response in JSON format.", 
                    prompt=str(search_response), 
                    model=self.openai_model, 
                    response_format=LendersGeminiSearchResponse
                )
                structured_response = openai_structured_response["data"]
            except Exception as e:
                logger.error(f"Error extracting structured response: {e}")
                return {"message": "Error extracting structured response", "status_code": 500}

        #LROI 3.4:Check if the structured response is not None
        if not structured_response:
            logger.error(f"Error extracting structured response: {openai_structured_response['error']}")
            return {"message": "Error extracting structured response", "status_code": 500}
        else:
            try:
                #LROI 3.5:Reformat the response based on the keys in the response format
                structured_response["id"] = lender_id
                structured_response["lender_name"] = lender_name
                structured_response["home_loan_roi"] = structured_response.pop("interest_rate_range")
                structured_response["lap_roi"] = structured_response.pop("loan_to_value")
                structured_response["updated_at"] = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y-%m-%d %H:%M:%S")
                logger.info(f"✅ Structured response created successfully")
                # breakpoint()
            except Exception as e:
                logger.error(f"Error reformatting structured response: {e}")
                return {"message": "Error reformatting structured response", "status_code": 500}

        #LROI 4:Save the structured response to the database
        try:
            database_response = database_service.save_unique_data(data=structured_response, table_name=table_name, update_if_exists=True)
            # logger.info(f"Database response: {database_response}")
            # breakpoint()
            return {"message": f"Data scraped & {database_response['status']} - {database_response['message']}", "status_code": 200}
        except Exception as e:
            logger.error(f"Error saving structured response: {e}")
            return {"message": f"Error saving structured response: {e}", "status_code": 500}

scrapelendersroi = ScrapeLendersROI()