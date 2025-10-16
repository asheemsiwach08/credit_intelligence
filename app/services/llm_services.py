import logging
import time
import random
from google import genai
from google.genai import types
from openai import OpenAI
from app.config.settings import settings
import requests

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


# class GeminiService:
#     """Service for handling Google Gemini AI interactions"""

#     def __init__(self):
#         """Initialize Gemini service with API key"""
#         self.api_key = settings.GEMINI_API_KEY
#         if not self.api_key:
#             logger.error("❌ GEMINI_API_KEY not found in environment variables")
#             raise ValueError("GEMINI_API_KEY is required")

#         # Initialize models
#         self.client = genai.Client(api_key=self.api_key)
#         if not self.client:
#             logger.error("❌ Failed to initialize Gemini client")
#             raise ValueError("Failed to initialize Gemini client")

#         # Define the grounding tool
#         self.grounding_tool = types.Tool(
#             google_search=types.GoogleSearch()
#         )

#         # Configure generation settings
#         self.config = types.GenerateContentConfig(
#             tools=[self.grounding_tool]
#         )

#         logger.info("✅ Gemini service initialized successfully")

#     def search_google(self, prompt, model: str = "gemini-2.0-flash", max_retries: int = None):
#         """Generate a search response using Gemini with retry logic"""
        
#         if max_retries is None:
#             max_retries = settings.GEMINI_RETRY_ATTEMPTS
        
#         for attempt in range(max_retries):
#             try:
#                 response = self.client.models.generate_content(
#                     model=model,
#                     contents=prompt,
#                     config=self.config,
#                 )
#                 break  # Success, exit retry loop
                
#             except Exception as e:
#                 error_str = str(e)
                
#                 # Check if it's a quota/rate limit error
#                 if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
#                     if attempt < max_retries - 1:  # Don't sleep on last attempt
#                         # Exponential backoff with jitter
#                         wait_time = (2 ** attempt) + random.uniform(0, 1)
#                         logger.warning(f"⚠️ Quota exhausted, retrying in {wait_time:.2f}s (attempt {attempt + 1}/{max_retries})")
#                         time.sleep(wait_time)
#                         continue
#                     else:
#                         logger.error(f"❌ Quota exhausted after {max_retries} attempts: {e}")
#                         return {
#                             "success": False,
#                             "data": None,
#                             "status": "quota_exhausted",
#                             "token_usage": {"prompt_token": 0, "completion_token": 0, "output_token": 0, "total_token": 0},
#                             "error": f"Quota exhausted: {error_str}"
#                         }
#                 else:
#                     # Non-quota error, don't retry
#                     logger.error(f"❌ Non-quota error: {e}")
#                     return {
#                         "success": False,
#                         "data": None,
#                         "status": "error",
#                         "token_usage": {"prompt_token": 0, "completion_token": 0, "output_token": 0, "total_token": 0},
#                         "error": str(e)
#                     }
        
#         if response.candidates:
#             try:
#                 for part in response.candidates[0].content.parts:
#                     if part.text is not None:
#                         return {
#                                 "success": True,
#                                 "data":part.text,
#                                 "status":"completed",
#                                 "token_usage":{
#                                     "prompt_token":response.usage_metadata.prompt_token_count,
#                                     "completion_token":response.usage_metadata.candidates_token_count, 
#                                     "output_token":0, 
#                                     "total_token":response.usage_metadata.total_token_count
#                                     },
#                                 "error": None
#                             }
                        
#                 else:
#                     return {
#                         "success": False,
#                         "data": None,
#                         "status":"completed",
#                         "token_usage":{"prompt_token":0,"completion_token":0, "output_token":0, "total_token":0},
#                         "error": None
#                     }
#             except Exception as e:
#                 logger.error(f"Error searching Google: {e}")
#                 return {
#                         "success": False,
#                         "data": None,
#                         "status":"completed",
#                         "token_usage":{"prompt_token":0,"completion_token":0, "output_token":0, "total_token":0},
#                         "error": str(e)
#                     }
                

class GeminiService:
    """Service for handling Google Gemini AI interactions"""

    def __init__(self):
        """Initialize Gemini service with API key"""
        self.api_key = settings.GEMINI_API_KEY
        if not self.api_key:
            logger.error("❌ GEMINI_API_KEY not found in environment variables")
            raise ValueError("GEMINI_API_KEY is required")

        # Keep SDK available if you use it elsewhere
        self.client = genai.Client(api_key=self.api_key)
        if not self.client:
            logger.error("❌ Failed to initialize Gemini client")
            raise ValueError("Failed to initialize Gemini client")

        # Tooling kept for compatibility (unused by REST call below)
        self.grounding_tool = types.Tool(google_search=types.GoogleSearch())
        self.config = types.GenerateContentConfig(tools=[self.grounding_tool])

        # >>> NEW: base for REST generateContent
        self._rest_base = "https://generativelanguage.googleapis.com/v1beta/models"

        logger.info("✅ Gemini service initialized successfully")

    # >>> NEW: small helpers for REST call + backoff
    def _rest_generate(self, *, model: str, text: str, quota_user: str | None, timeout: float = 30.0):
        """Raw REST call so we can send X-Goog-Quota-User and read Retry-After/usage."""
        url = f"{self._rest_base}/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        if quota_user:
            headers["X-Goog-Quota-User"] = quota_user
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            # If you want search tool via REST later:
            # "tools": [{"googleSearch": {}}]
        }
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:2000]}
        return r.status_code, body, dict(r.headers)

    def _backoff_seconds(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(0.5, float(retry_after))
            except ValueError:
                pass
        return min(60.0, (2 ** attempt) + random.random())  # jittered exponential

    def search_google(
        self,
        prompt,
        model: str = "gemini-2.0-flash",
        max_retries: int = None,
        quota_user: str | None = None,   # <<< NEW: partition bucket per caller
    ):
        """Generate response using Gemini with proper quota partitioning + backoff."""
        if max_retries is None:
            max_retries = settings.GEMINI_RETRY_ATTEMPTS

        attempt = 0
        while True:
            attempt += 1
            code, body, headers = self._rest_generate(model=model, text=prompt, quota_user=quota_user)
            retry_after = headers.get("Retry-After")

            err = body.get("error") or {}
            status = err.get("status")
            message = err.get("message")
            usage = body.get("usageMetadata") or {}

            # Structured, safe log
            logger.info({
                "evt": "gemini_call",
                "model": model,
                "code": code,
                "attempt": attempt,
                "retry_after": retry_after,
                "status": status,
                "message": message,
                "usage": usage,
                "quota_user": quota_user,
            })

            # Success
            if code == 200 and not err:
                text_out = None
                try:
                    text_out = body["candidates"][0]["content"]["parts"][0].get("text")
                except Exception:
                    pass
                return {
                    "success": True,
                    "data": text_out,
                    "status": "completed",
                    "token_usage": {
                        "prompt_token": usage.get("promptTokenCount", 0),
                        "completion_token": usage.get("candidatesTokenCount", 0),
                        "output_token": 0,
                        "total_token": usage.get("totalTokenCount", 0),
                    },
                    "http_code": code,
                    "error": None,
                }

            # Non-retriable 4xx (except 429)
            if code != 429 and 400 <= code < 500:
                return {
                    "success": False,
                    "data": None,
                    "status": status or "client_error",
                    "token_usage": {
                        "prompt_token": usage.get("promptTokenCount", 0),
                        "completion_token": usage.get("candidatesTokenCount", 0),
                        "output_token": 0,
                        "total_token": usage.get("totalTokenCount", 0),
                    },
                    "http_code": code,
                    "error": message or body,
                }

            # Retriable (429/5xx)
            if attempt >= (max_retries or 3):
                exhausted = (code == 429) or (status == "RESOURCE_EXHAUSTED")
                return {
                    "success": False,
                    "data": None,
                    "status": "quota_exhausted" if exhausted else (status or "server_error"),
                    "token_usage": {
                        "prompt_token": usage.get("promptTokenCount", 0),
                        "completion_token": usage.get("candidatesTokenCount", 0),
                        "output_token": 0,
                        "total_token": usage.get("totalTokenCount", 0),
                    },
                    "http_code": code,
                    "error": f"{code} {status or ''} {message or ''}".strip(),
                }

            wait = self._backoff_seconds(attempt, retry_after)
            logger.warning(f"⚠️ Quota/Server issue (code={code}, status={status}). Retrying in {wait:.2f}s (attempt {attempt}/{max_retries})")
            time.sleep(wait)


openai_analyzer = OpenAIAnalyzer()
gemini_service = GeminiService()
