import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException

from app.services.lenders_roi import scrapelendersroi
from app.models.schemas import  SnifferLendersRoiRequest
from app.services.database_service import database_service


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/sniffer", tags=["sniffer lenders roi"])

#Method to process a single lender 
def process_single_lender(lender_data, table_name):
    """Process a single lender - wrapper for thread execution"""
    try:
        lender_name = lender_data.get("lender_name", "")
        lender_id = lender_data.get("id", "")
        
        logger.info(f"Processing lender: {lender_name}")
        result = scrapelendersroi.get_lenders_roi(
            lender_name=lender_name,
            lender_id=lender_id,
            table_name=table_name
        )
        logger.info(f"✅ Completed processing lender: {lender_name}")
        return {"status": "success", "lender": lender_name, "result": result}
    except Exception as e:
        logger.error(f"❌ Error processing lender {lender_data.get('lender_name', 'Unknown')}: {e}")
        return {"status": "error", "lender": lender_data.get('lender_name', 'Unknown'), "error": str(e)}

#Method to process lenders in parallel
def process_lenders_parallel(lenders_data, table_name, max_concurrent=5):
    """Process lenders in parallel with limited concurrency"""
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        # Submit all tasks
        future_to_lender = {
            executor.submit(process_single_lender, lender, table_name): lender 
            for lender in lenders_data
        }
        
        # Process completed tasks
        for future in as_completed(future_to_lender):
            lender = future_to_lender[future]
            try:
                result = future.result()
                results.append(result)
                logger.info(f"✅ Completed {len(results)}/{len(lenders_data)} lenders")
            except Exception as e:
                logger.error(f"❌ Error in parallel processing for {lender.get('lender_name', 'Unknown')}: {e}")
                results.append({"status": "error", "lender": lender.get('lender_name', 'Unknown'), "error": str(e)})
    
    return results

#Method to scrape lenders ROI
@router.post("/lenders_roi")
def scrape_lenders_roi(request: SnifferLendersRoiRequest):

    # Validate the request
    if not request.table_name:
        logger.error("❌ Table name is required. Please check the table name")
        raise HTTPException(status_code=400, detail="Table name is required. Please check the table name")

    logger.info(f"Lenders ROI request: {request}")

    # Extract the lender name from the database
    try:
        lenders_sql_response = database_service.run_sql(query=f"Select id, lender_name from {request.table_name} where updated_at <= NOW() - INTERVAL '{request.interval} day'")
    except Exception as e:
        logger.debug(f"❌ Error extracting data for {request.table_name} table from database: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if not lenders_sql_response["data"]:
        logger.debug(f"❌ No data found from {request.table_name} table in database for the selected interval. Please check the interval and table name")
        raise HTTPException(status_code=404, detail=f"No data found from {request.table_name} table in database for the selected interval. Please check the interval and table name")
    else:
        lenders_data = lenders_sql_response["data"]
        logger.info(f"✅ Found {len(lenders_data)} lenders to process")
        
        # Process lenders in parallel with limited concurrency
        results = process_lenders_parallel(lenders_data, request.table_name, max_concurrent=5)
        
        # Summary of results
        successful = len([r for r in results if r["status"] == "success"])
        failed = len([r for r in results if r["status"] == "error"])
        
        logger.info(f"✅ Processing completed: {successful} successful, {failed} failed")
        
        return {
            "message": f"Processed {len(lenders_data)} lenders",
            "successful": successful,
            "failed": failed,
            "results": results
        }


