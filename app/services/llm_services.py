import logging
from typing import Optional
from pydantic import BaseModel
from google import genai
from google.genai import types
from openai import OpenAI
from app.config.settings import settings

logger = logging.getLogger(__name__)

class OpenAIAnalyzer:
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.model = settings.SNIFFER_ROI_OPENAI_MODEL
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS
        self.client = OpenAI(api_key=self.api_key)

        if not self.client:
            raise ValueError("Failed to initialize OpenAI client")

        logger.info("✅ OpenAI service initialized successfully")

    def analyze_context(self, model: str = None, messages: list = None, response_format=None):
        if not model:
            model = self.model

        try:
            response = self.client.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_format,
                # temperature=temperature
            )
            return {
                    "success": True,
                    "data":response.choices[0].message.parsed.model_dump(),
                    "status":"Not defined",
                    "token_usage":{"prompt_token":response.usage.prompt_tokens,"completion_token":response.usage.completion_tokens, "output_token":0, "total_token":response.usage.total_tokens},
                    "error": None
                }
        except Exception as e:
            return {
                    "success": False,
                    "data":None,
                    "status":"Error",
                    "token_usage":{"prompt_token":0,"completion_token":0, "output_token":0, "total_token":0},
                    "error": str(e)
                }


        
    # Function to send a prompt to GPT model for extracting data
    def get_structured_response(self, system_message, prompt, model: str = None, response_format=None):
        try:
            response = self.client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,  # creativity
                response_format=response_format
            )
            
            return {
                    "success": True,
                    "data":response.choices[0].message.parsed.model_dump(),
                    "status":"Not defined",
                    "token_usage":{
                        "prompt_token":response.usage.prompt_tokens,
                        "completion_token":response.usage.completion_tokens, 
                        "output_token":0, 
                        "total_token":response.usage.total_tokens
                        },
                    "error": None
                }
        except Exception as e:
            return {
                    "success": False,
                    "data":None,
                    "status":"Error",
                    "token_usage":{"prompt_token":0,"completion_token":0, "output_token":0, "total_token":0},
                    "error": str(e)
                }

    def structured_output(self, prompt, model: str = None, response_format=None):
        try:
            response = self.client.responses.parse(
                model=model,
                temperature=0.7,
                input=[
                        {"role": "system", "content": "Extract entities from the input text"},
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                text_format=response_format
            )
            if response.output_parsed:
                return {
                    "success": True,
                    "data":response.output_parsed.model_dump(),
                    "status":response.status,
                    "token_usage":{
                        "prompt_token":response.usage.input_tokens, 
                        "completion_token":0,
                        "output_token":response.usage.output_tokens, 
                        "total_token":response.usage.total_tokens
                        },
                    "error": response.error
                }
            
        except Exception as e:
            return {
                    "success": False,
                    "data":None,
                    "status":"Error",
                    "token_usage":{"input_token":0, "output_token":0, "total_token":0},
                    "error": str(e)
                }


class GeminiService:
    """Service for handling Google Gemini AI interactions"""

    def __init__(self):
        """Initialize Gemini service with multiple API keys"""
        # API Keys
        self.single_api_key = settings.GEMINI_SINGLE_API_KEY
        self.multi_api_key = settings.GEMINI_MULTI_API_KEY
        self.fallback_api_key = settings.GEMINI_API_KEY
        
        # Models
        self.gemini_single_search_model = settings.GEMINI_SINGLE_SEARCH_MODEL
        self.gemini_multi_search_model = settings.GEMINI_MULTI_SEARCH_MODEL
        
        # Validate API keys
        if not (self.single_api_key or self.multi_api_key or self.fallback_api_key):
            logger.error("❌ No Gemini API keys found in environment variables")
            raise ValueError("At least one Gemini API key is required")

        # Initialize clients for both API keys
        self.single_client = None
        self.multi_client = None
        
        if self.single_api_key:
            self.single_client = genai.Client(api_key=self.single_api_key)
        
        if self.multi_api_key:
            self.multi_client = genai.Client(api_key=self.multi_api_key)
        
        # Fallback client
        if not self.single_client and not self.multi_client:
            self.single_client = genai.Client(api_key=self.fallback_api_key)
            self.multi_client = self.single_client

        # Define the grounding tool
        self.grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )

        self.config = types.GenerateContentConfig(
            tools=[self.grounding_tool]
            )

        logger.info("✅ Gemini service initialized successfully")



    # # Configure generation settings
    # def set_model_response(self, model_response_schema:Optional[BaseModel] = None):

    #     if model_response_schema:
    #         config = types.GenerateContentConfigDict(
    #         response_mime_type="application/json",
    #         response_schema=model_response_schema,
    #         tools=[self.grounding_tool]
    #         )
    #         return config
    #     else:
    #         config = types.GenerateContentConfig(
    #         tools=[self.grounding_tool]
    #         )
    #         return config


    def search_google(self, prompt, model: str = None):
        """Generate a search response using Gemini with appropriate API key"""
        if not model:
            model = self.gemini_single_search_model

        # Select the appropriate client based on model type
        if model == self.gemini_single_search_model and self.single_client:
            client = self.single_client
            logger.debug(f"🔑 Using single API key for model: {model}")
        elif model == self.gemini_multi_search_model and self.multi_client:
            client = self.multi_client
            logger.debug(f"🔑 Using multi API key for model: {model}")
        else:
            # Fallback to available client
            client = self.single_client or self.multi_client
            logger.warning(f"⚠️ Using fallback client for model: {model}")

        response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=self.config,
            )

        if response.candidates:
            try:
                all_data = ""
                for part in response.candidates[0].content.parts:
                    if part.text is not None:
                        all_data += part.text
                return {
                            "success": True,
                            "data":all_data,
                            "status":"completed",
                            "token_usage":{
                                "prompt_token":response.usage_metadata.prompt_token_count,
                                "completion_token":response.usage_metadata.candidates_token_count, 
                                "output_token":0, 
                                "total_token":response.usage_metadata.total_token_count
                                },
                            "error": None
                        }
                        
            except Exception as e:
                logger.error(f"Error searching Google: {e}")
                return {
                        "success": False,
                        "data": None,
                        "status":"completed",
                        "token_usage":{"prompt_token":0,"completion_token":0, "output_token":0, "total_token":0},
                        "error": str(e)
                    }
                


openai_analyzer = OpenAIAnalyzer()
gemini_service = GeminiService()
