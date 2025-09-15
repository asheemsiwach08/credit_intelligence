import logging

from fastapi import FastAPI
from app.api.router import credit_router
from app.api.health_router import health_router
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

app = FastAPI(
    title="Credit Intelligence API",
    description="API for generating credit intelligence reports",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(credit_router)
app.include_router(health_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=9000, 
        reload=True
    ) 
