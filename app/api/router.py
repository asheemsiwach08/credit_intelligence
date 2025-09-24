from fastapi import APIRouter
from app.api.endpoints import health_check, credit_intelligence, sniffer_lenders_roi

# Create main API router
api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(health_check.router)
api_router.include_router(credit_intelligence.router)
api_router.include_router(sniffer_lenders_roi.router)