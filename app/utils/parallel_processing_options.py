"""
Different parallel processing approaches for 178 lenders based on resources
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from app.services.database_service import database_service
from app.services.lenders_roi import scrapelendersroi

def get_lenders_to_process():
    """Get lenders that need processing"""
    response = database_service.run_sql(
        query="SELECT id, lender_name FROM lenders WHERE updated_at <= NOW() - INTERVAL '1 day'"
    )
    return response["data"] if response["status"] == "success" else []

# Option 1: Conservative (Limited resources)
def process_conservative(lenders_data, table_name, max_concurrent=3):
    """
    Best for: Limited CPU/Memory, Stable processing
    Concurrent workers: 3
    Good for: Shared servers, low-end machines
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_lender = {
            executor.submit(process_single_lender, lender, table_name): lender 
            for lender in lenders_data
        }
        
        for future in as_completed(future_to_lender):
            result = future.result()
            results.append(result)
            print(f"✅ Completed {len(results)}/{len(lenders_data)} lenders")
            
            # Add small delay to prevent overwhelming
            time.sleep(0.5)
    
    return results

# Option 2: Balanced (Medium resources)
def process_balanced(lenders_data, table_name, max_concurrent=5):
    """
    Best for: Moderate CPU/Memory, Good balance
    Concurrent workers: 5
    Good for: Standard servers, development machines
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_lender = {
            executor.submit(process_single_lender, lender, table_name): lender 
            for lender in lenders_data
        }
        
        for future in as_completed(future_to_lender):
            result = future.result()
            results.append(result)
            print(f"✅ Completed {len(results)}/{len(lenders_data)} lenders")
    
    return results

# Option 3: Batch Processing (Very limited resources)
def process_in_batches(lenders_data, table_name, batch_size=10):
    """
    Best for: Very limited resources, need to process in chunks
    Processes: batch_size lenders at a time
    Good for: Avoiding memory issues, rate limiting
    """
    results = []
    total_lenders = len(lenders_data)
    
    for i in range(0, total_lenders, batch_size):
        batch = lenders_data[i:i+batch_size]
        print(f"🔄 Processing batch {i//batch_size + 1}/{(total_lenders + batch_size - 1)//batch_size}")
        
        # Process batch sequentially
        for lender in batch:
            try:
                result = process_single_lender(lender, table_name)
                results.append(result)
                print(f"  ✅ {lender['lender_name']}")
            except Exception as e:
                results.append({"status": "error", "lender": lender['lender_name'], "error": str(e)})
                print(f"  ❌ {lender['lender_name']}: {e}")
        
        # Rest between batches
        if i + batch_size < total_lenders:
            print(f"⏸️  Resting for 2 seconds...")
            time.sleep(2)
    
    return results

# Option 4: Aggressive (High resources)
def process_aggressive(lenders_data, table_name, max_concurrent=10):
    """
    Best for: High CPU/Memory, Fast processing
    Concurrent workers: 10
    Good for: Powerful servers, cloud instances
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        future_to_lender = {
            executor.submit(process_single_lender, lender, table_name): lender 
            for lender in lenders_data
        }
        
        for future in as_completed(future_to_lender):
            result = future.result()
            results.append(result)
            if len(results) % 10 == 0:  # Log every 10 completions
                print(f"✅ Completed {len(results)}/{len(lenders_data)} lenders")
    
    return results

def process_single_lender(lender_data, table_name):
    """Process a single lender"""
    try:
        lender_name = lender_data.get("lender_name", "")
        lender_id = lender_data.get("id", "")
        
        result = scrapelendersroi.get_lenders_roi(
            lender_name=lender_name,
            lender_id=lender_id,
            table_name=table_name
        )
        return {"status": "success", "lender": lender_name, "result": result}
    except Exception as e:
        return {"status": "error", "lender": lender_data.get('lender_name', 'Unknown'), "error": str(e)}

def main():
    """Test different approaches"""
    lenders_data = get_lenders_to_process()
    print(f"📊 Found {len(lenders_data)} lenders to process")
    
    if not lenders_data:
        print("❌ No lenders found")
        return
    
    # Choose your approach based on resources:
    table_name = "lenders_roi_data"
    
    print("\n🚀 Choose your processing approach:")
    print("1. Conservative (3 concurrent) - Limited resources")
    print("2. Balanced (5 concurrent) - Medium resources") 
    print("3. Batch (10 per batch) - Very limited resources")
    print("4. Aggressive (10 concurrent) - High resources")
    
    choice = input("Enter choice (1-4): ").strip()
    
    start_time = time.time()
    
    if choice == "1":
        results = process_conservative(lenders_data, table_name)
    elif choice == "2":
        results = process_balanced(lenders_data, table_name)
    elif choice == "3":
        results = process_in_batches(lenders_data, table_name)
    elif choice == "4":
        results = process_aggressive(lenders_data, table_name)
    else:
        print("Invalid choice, using balanced approach")
        results = process_balanced(lenders_data, table_name)
    
    end_time = time.time()
    
    # Summary
    successful = len([r for r in results if r["status"] == "success"])
    failed = len([r for r in results if r["status"] == "error"])
    
    print(f"\n📈 Processing Summary:")
    print(f"⏱️  Total time: {end_time - start_time:.2f} seconds")
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Success rate: {(successful/len(results)*100):.1f}%")

if __name__ == "__main__":
    main()
