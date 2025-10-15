#!/usr/bin/env python3
"""
Gemini API Quota Monitor and Management Script

This script helps you monitor and manage your Gemini API usage to avoid quota exhaustion.
"""

import os
import time
import logging
from datetime import datetime
from app.services.llm_services import GeminiService
from app.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gemini_quota():
    """Test if Gemini API is accessible and check quota status"""
    try:
        gemini_service = GeminiService()
        
        # Simple test query
        test_prompt = "What is the current date?"
        logger.info("🧪 Testing Gemini API with simple query...")
        
        response = gemini_service.search_google(test_prompt)
        
        if response.get("success"):
            logger.info("✅ Gemini API is working correctly")
            logger.info(f"📊 Token usage: {response.get('token_usage', {})}")
            return True
        else:
            logger.error(f"❌ Gemini API test failed: {response.get('error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error testing Gemini API: {e}")
        return False

def check_quota_status():
    """Check current quota status"""
    logger.info("🔍 Checking Gemini API quota status...")
    
    # Test with a simple query
    if test_gemini_quota():
        logger.info("✅ Quota appears to be available")
        return True
    else:
        logger.error("❌ Quota may be exhausted or API key invalid")
        return False

def get_quota_recommendations():
    """Provide recommendations for managing quota"""
    logger.info("📋 Quota Management Recommendations:")
    print("""
    🎯 IMMEDIATE ACTIONS:
    1. Check Google Cloud Console Quotas: https://console.cloud.google.com/iam-admin/quotas
    2. Look for "Generative Language API" quotas
    3. Request quota increase if needed
    
    🔧 CODE OPTIMIZATIONS:
    1. Reduce GEMINI_MAX_WORKERS in environment variables (default: 2)
    2. Increase GEMINI_RETRY_ATTEMPTS for better retry handling (default: 3)
    3. Add delays between API calls
    
    📊 MONITORING:
    1. Monitor token usage in logs
    2. Set up alerts for quota exhaustion
    3. Consider implementing caching for repeated queries
    
    💡 COST OPTIMIZATION:
    1. Use shorter, more focused prompts
    2. Cache results for similar queries
    3. Consider using different models for different use cases
    """)

def main():
    """Main function to run quota monitoring"""
    logger.info("🚀 Starting Gemini API Quota Monitor")
    logger.info(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if API key is configured
    if not settings.GEMINI_API_KEY:
        logger.error("❌ GEMINI_API_KEY not found in environment variables")
        logger.info("💡 Please set GEMINI_API_KEY in your environment or .env file")
        return
    
    # Test quota status
    quota_ok = check_quota_status()
    
    if not quota_ok:
        logger.warning("⚠️ Quota issues detected!")
        get_quota_recommendations()
    else:
        logger.info("✅ Quota status looks good!")
    
    # Show current configuration
    logger.info("⚙️ Current Configuration:")
    logger.info(f"   GEMINI_MAX_WORKERS: {settings.GEMINI_MAX_WORKERS}")
    logger.info(f"   GEMINI_RETRY_ATTEMPTS: {settings.GEMINI_RETRY_ATTEMPTS}")
    logger.info(f"   GEMINI_SEARCH_MODEL: {settings.GEMINI_SEARCH_MODEL}")

if __name__ == "__main__":
    main()
