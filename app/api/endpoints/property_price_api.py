
import uuid
import logging
from typing import Optional, List
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, HTTPException
from app.services.database_service import database_service
from app.services.property_price_service import property_price_service

logger = logging.getLogger(__name__)

# Initializing the router
router = APIRouter(prefix="/ai", tags=["property price"])

# -------------------------------------------------------------------------------------------------------- #
                                    # Pydantic Models #
# -------------------------------------------------------------------------------------------------------- #


class PropertyPricesRequest(BaseModel):
    table_name: Optional[str] = "approved_projects"
    interval: Optional[int] = 1

class PropertyPricesResponse(BaseModel):
    message: str
    successful: int
    failed: int
    results: list

class PropertyPriceResponse(BaseModel):
    status: str
    project_name: str
    message: str
    data: List[dict]

class PropertyPriceRequest(BaseModel):
    id: Optional[str] = None
    project_name: str
    city: Optional[str] = None
    table_name: Optional[str] = "approved_projects"
    search_type: Optional[str] = "multi"  # "single", "multi", or "auto" (auto-detect)

# -------------------------------------------------------------------------------------------------------- #
                               # Parallel Processing Functions #
# -------------------------------------------------------------------------------------------------------- #

#Method to process a single property 
def process_single_project(property_detail):
    """Process a single property - wrapper for thread execution"""

    property_id = property_detail.get("id",None)
    property_name = property_detail.get("project_name","")
    property_location = property_detail.get("city","")
    table_name = property_detail.get("table_name", "approved_projects")
    search_type = property_detail.get("search_type", "multi")

    new_record = True if not property_id else False  # set the variable for differentiating the new record and the existing record
    
    # Set search type based on use case (auto-detect or use provided)
    if search_type == "auto":
        search_type = "single" if new_record else "multi"  # Single for new properties, multi for updates
    
    logger.info(f"Method Inputs: {property_id}, {property_name}, {property_location}, {table_name}, {new_record}, search_type={search_type}")

    # Finding the Property Price and other details
    try:
        logger.info(f"Processing project: {property_name} with {search_type} search")
        find_property_price_result = property_price_service.find_property_price(
            property_id=property_id, 
            property_name=property_name, 
            property_location=property_location,
            new_record=new_record,
            search_type=search_type,
            # table_name=table_name
        )
        find_property_data = find_property_price_result.get("data",None)
        if not find_property_data.get("property_found"):
            logger.info(f"No record found for the mentioned property. Please check the property name and location.")
            return {"status": "success", "property_name": property_name, "message": "No record found for the mentioned property. Please check the property name and location."}
    except Exception as e:
        logger.error(f"❌ Error processing property {property_name} for location {property_location}: {e}")
        return {"status": "error", "property_name": property_name, "message": str(e)}

    # Updating Records to the Database
    try:
        generated_data_to_save = find_property_price_result.get("data",{})
        # logger.info(f"Generated data to save: {generated_data_to_save}")

        data_to_save = property_price_service.generate_data_to_save(data_to_update=generated_data_to_save, new_record=new_record)
        db_response = property_price_service.updating_records_to_db(data_to_save=data_to_save, new_record=new_record)
        
        logger.info(f"✅ Completed processing property: {property_name}")

        data_for_ui = []
        if new_record:
            for property in generated_data_to_save.get("properties",[]):
                data_for_ui.append({
                "property_name": property.get("project_name",""), 
                "lenders_count": len(property.get("lenders",[])),
                "lenders_names": property.get("lenders",[]),
                "builder_name": property.get("builder_name",""), 
                "city": property.get("city",""),
                "lenders_id": db_response.get("lenders_id",[])
                })
        else:
            data_for_ui = []

        return {"status": "success", "property_name": property_name, "message": db_response.get("message"), "data": data_for_ui}
    except Exception as e:
        logger.error(f"❌ Error generating data to save for property {property_name} for location {property_location}: {e}")
        return {"status": "error", "property_name": property_name, "message": str(e)}



#Method to process properties in parallel
def process_properties_parallel(property_details, max_concurrent=5):
    """Process properties in parallel with limited concurrency"""
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # Submit all tasks
        future_to_property = {
            executor.submit(process_single_project, property): property
            for property in property_details
        }
        
        # Process completed tasks
        for future in as_completed(future_to_property):
            property = future_to_property[future]
            try:
                result = future.result()
                results.append(result)
                logger.info(f"✅ Completed {len(results)}/{len(property_details)} properties")
            except Exception as e:
                logger.error(f"❌ Error in parallel processing for {property.get('property_name', 'Unknown')}: {e}")
                results.append({"status": "error", "property_name": property.get('property_name', 'Unknown'), "message": str(e)})
    
    return results


###########################################################################################################
                               #  API for Getting Property Price #
###########################################################################################################

@router.post("/property_price", response_model=PropertyPriceResponse)
def get_property_price(request: PropertyPriceRequest):

    # Validate the request
    if not request.project_name:
        logger.error("❌ Project name is required. Please check the project name")
        raise HTTPException(status_code=400, detail="Project name is required. Please check the project name")
    # if not request.city:
    #     logger.error("❌ City is required. Please check the city")
    #     raise HTTPException(status_code=400, detail="City is required. Please check the city")

    logger.info(f"Property price request: {request.id}, {request.project_name}, {request.city}")

    result = process_single_project(dict(request))

    return PropertyPriceResponse(
        status=result.get("status"),
        project_name=request.project_name,
        message=result.get("message"),
        data=result.get("data",[])
    )

# -------------------------------------------------------------------------------------------------------- #
                                # API to get Multiple Property Prices #
# -------------------------------------------------------------------------------------------------------- #
@router.post("/property_prices",response_model=PropertyPricesResponse)
def get_property_prices(request: PropertyPricesRequest):

    # Validate the request
    if not request.table_name:
        logger.error("❌ Table name is required. Please check the table name")
        raise HTTPException(status_code=400, detail="Table name is required. Please check the table name")

    logger.info(f"Approved Projects Price request: {request}")

    # Extract the project name and city from the database
    try:
        projects_sql_response = database_service.run_sql(query=f"Select id, project_name, city from {request.table_name} where updated_at <= NOW() - INTERVAL '{request.interval} day' limit 1")
    except Exception as e:
        logger.debug(f"❌ Error extracting data for {request.table_name} table from database: {e}. Please check the table name, and columns along with the interval.")
        raise HTTPException(status_code=500, detail=str(e))

    if not projects_sql_response["data"]:
        logger.debug(f"❌ No data found from {request.table_name} table in database for the selected interval. Please check the interval and table name")
        raise HTTPException(status_code=404, detail=f"No data found from {request.table_name} table in database for the selected interval. Please check the interval and table name")
    else:
        approved_projects_data = projects_sql_response["data"]
        logger.info(f"✅ Found {len(approved_projects_data)} projects to process")
   
     # Process lenders in parallel with limited concurrency
    results = process_properties_parallel(approved_projects_data, max_concurrent=5)
    
    # Summary of results
    successful = len([r for r in results if r["status"] == "success"])
    failed = len([r for r in results if r["status"] == "error"])
    
    logger.info(f"✅ Processing completed: {successful} successful, {failed} failed")
    
    return PropertyPricesResponse(
        message=f"Processed {len(approved_projects_data)} projects",
        successful=successful,
        failed=failed,
        results=results
    )