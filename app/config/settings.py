import os
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

class Settings:
    "Application Settings"

    # API configuration
    API_TITLE = "Credit Intelligence & Sniffer AI"
    API_DESCRIPTION = "Credit Intelligence & Sniffer AI is a tool that allows you to scrape and analyze data."
    API_VERSION = "1.0.0"

    # Server configuration
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = os.getenv("PORT", "9000")
    RELOAD = os.getenv("RELOAD", "true")
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"

    # S3 configuration
    S3_BUCKET = os.getenv("S3_BUCKET")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION")

    # PostgreSQL configuration
    POSTGRES_HOST = os.getenv("POSTGRES_HOST")

    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "postgres")

    # Table name for credit intelligence
    POSTGRES_TABLE = os.getenv("POSTGRES_TABLE", "credit_intelligence")

    # Firecrawl API Key
    FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

    # OpenAI API Key
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    CREDIT_INTELLIGENCE_OPENAI_MODEL = os.getenv("CREDIT_INTELLIGENCE_OPENAI_MODEL", "gpt-4.1-nano-2025-04-14")  # Credit Intelligence OpenAI Model
    SNIFFER_ROI_OPENAI_MODEL = os.getenv("SNIFFER_ROI_OPENAI_MODEL", "gpt-4o-mini")  # Sniffer ROI OpenAI Model
    OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "1000"))

    # Supabase Configuration
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    # Gemini API Key
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.0-flash")  # Gemini Search Model



# Global Settings Instance
settings = Settings()