import time
import logging  
import uuid
from typing import Dict, Optional, List

from fastapi import HTTPException
from app.config.settings import settings
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone


logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for handling Supabase database operations"""
    
    def __init__(self):
        self.supabase_url = settings.SUPABASE_URL
        self.supabase_service_role_key = settings.SUPABASE_SERVICE_ROLE_KEY 
        
        if not self.supabase_url or not self.supabase_service_role_key:
            logger.error("❌ WARNING: Supabase credentials not configured.")
            logger.error("Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables.")
            self.client = None
        else:
            try:
                self.client = create_client(self.supabase_url, self.supabase_service_role_key)
            except Exception as e:
                logger.error(f"❌ Error initializing Supabase client: {e}")
                self.client = None

    
    def save_data(self, data: dict, table_name: str):
        """Save data to the database"""
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return None
        
        try:
            response = self.client.table(table_name).insert(data).execute()
            return response
        except Exception as e:
            logger.error(f"❌ Error saving data to {table_name}: {e}")
            return None
    
    def _add_uuid_if_missing(self, data: dict, primary_key: str = "id") -> dict:
        """Add UUID to primary key if missing or null"""
        # Always use "id" as primary key
        primary_key = "id"
        if primary_key not in data or data[primary_key] in [None, ""]:
            data[primary_key] = str(uuid.uuid4())
            logger.info(f"✅ Generated UUID for missing primary key '{primary_key}': {data[primary_key]}")
        return data

    def save_unique_data(self, data: dict, table_name: str, update_if_exists: bool = True):
        """
        Save data to database with duplicate prevention
        
        Args:
            data (dict): Data to save
            table_name (str): Database table name
            primary_key (str): Field name to use as primary key for uniqueness check
            update_if_exists (bool): Whether to update existing record or skip
            
        Returns:
            dict: Result with status and details
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {"status": "error", "message": "Database client not initialized"}

        # Add UUID if primary key is missing (always use "id")
        data = self._add_uuid_if_missing(data, "id")
        primary_value = data["id"]
        
        # try:
        # Check if record already exists (always use "id" as primary key)
        existing_record = self.client.table(table_name).select("*").eq("id", primary_value).execute()

        if existing_record.data:
            # Record exists
            if update_if_exists:
                # Update existing record
                response = self.client.table(table_name).update(data).eq("id", primary_value).execute()
                logger.info(f"✅ Updated existing record in {table_name} where id={primary_value}")

                return {
                    "status": "updated",
                    "message": f"Record updated successfully",
                    "primary_key": "id",
                    "primary_value": primary_value,
                    "data": response.data
                }
            else:
                # Skip duplicate
                logger.info(f"❌ Skipped duplicate record in {table_name} where id={primary_value}")
                return {
                    "status": "skipped",
                    "message": f"Record already exists",
                    "primary_key": "id",
                    "primary_value": primary_value,
                    "existing_data": existing_record.data[0]
                }
        else:
            # Insert new record
            response = self.client.table(table_name).insert(data).execute()
            logger.info(f"✅ Inserted new record in {table_name}")
            return {
                "status": "inserted",
                "message": f"New record created successfully",
                "primary_key": "id",
                "primary_value": primary_value,
                "data": response.data
            }
                
        # except Exception as e:
        #     logger.error(f"Error saving unique data to {table_name}: {e}")
        #     return {"status": "error", "message": str(e)}
    
    def save_batch_unique_data(self, data_list: List[dict], table_name: str, update_if_exists: bool = True):
        """
        Save multiple records with duplicate prevention
        
        Args:
            data_list (List[dict]): List of data records to save
            table_name (str): Database table name
            primary_key (str): Field name to use as primary key for uniqueness check    # TODO: Change this to unique_key
            update_if_exists (bool): Whether to update existing records or skip
            
        Returns:
            dict: Batch operation results
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {"status": "error", "message": "Database client not initialized"}
        
        results = {
            "total_records": len(data_list),
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }
        
        for i, data in enumerate(data_list):
            try:
                # Add UUID if primary key is missing (always use "id")
                data = self._add_uuid_if_missing(data, "id")
                result = self.save_unique_data(data, table_name, update_if_exists)
                
                if result["status"] == "inserted":
                    results["inserted"] += 1
                elif result["status"] == "updated":
                    results["updated"] += 1
                elif result["status"] == "skipped":
                    results["skipped"] += 1
                else:
                    results["errors"] += 1
                
                results["details"].append({
                    "index": i,
                    "primary_key":"id",
                    "status": result["status"],
                    "message": result["message"]
                })
                
            except Exception as e:
                results["errors"] += 1
                results["details"].append({
                    "index": i,
                    "primary_key": "id",
                    "status": "error",
                    "message": str(e)
                })
        
        logger.info(f"✅ Batch operation completed: {results['inserted']} inserted, {results['updated']} updated, {results['skipped']} skipped, {results['errors']} errors")
        return results
    
    def save_with_multiple_key_check(self, data: dict, table_name: str, unique_fields: List[str], update_if_exists: bool = True):
        """
        Save data with multiple field uniqueness check
        
        Args:
            data (dict): Data to save
            table_name (str): Database table name  
            unique_fields (List[str]): List of field names that together make a unique record
            update_if_exists (bool): Whether to update existing record or skip
            
        Returns:
            dict: Result with status and details
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {"status": "error", "message": "Database client not initialized"}
        
        # Check if all unique fields exist in data
        missing_fields = [field for field in unique_fields if field not in data]
        if missing_fields:
            logger.error(f"❌ Unique fields {missing_fields} not found in data")
            return {"status": "error", "message": f"Missing unique fields: {missing_fields}"}
        
        try:
            # Build query to check for existing record
            query = self.client.table(table_name).select("*")
            
            for field in unique_fields:
                query = query.eq(field, data[field])
            
            existing_record = query.execute()
            
            if existing_record.data:
                # Record exists
                if update_if_exists:
                    # Update existing record
                    update_query = self.client.table(table_name).update(data)
                    for field in unique_fields:
                        update_query = update_query.eq(field, data[field])
                    
                    response = update_query.execute()
                    logger.info(f"✅ Updated existing record in {table_name} with unique fields {unique_fields}")
                    return {
                        "status": "updated",
                        "message": f"Record updated successfully",
                        "unique_fields": unique_fields,
                        "unique_values": {field: data[field] for field in unique_fields},
                        "data": response.data
                    }
                else:
                    # Skip duplicate
                    logger.info(f"❌ Skipped duplicate record in {table_name} with unique fields {unique_fields}")
                    return {
                        "status": "skipped",
                        "message": f"Record already exists",
                        "unique_fields": unique_fields,
                        "unique_values": {field: data[field] for field in unique_fields},
                        "existing_data": existing_record.data[0]
                    }
            else:
                # Insert new record
                response = self.client.table(table_name).insert(data).execute()
                logger.info(f"✅ Inserted new record in {table_name}")
                return {
                    "status": "inserted",
                    "message": f"New record created successfully",
                    "unique_fields": unique_fields,
                    "unique_values": {field: data[field] for field in unique_fields},
                    "data": response.data
                }
                
        except Exception as e:
            logger.error(f"❌ Error saving data with multiple key check to {table_name}: {e}")
            return {"status": "error", "message": str(e)}
    
    def get_existing_records(self, table_name: str, field_name: str, values: List[str]):
        """
        Get existing records by field values
        
        Args:
            table_name (str): Database table name
            field_name (str): Field name to check
            values (List[str]): List of values to check
            
        Returns:
            dict: Existing records grouped by field value
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {}
        
        try:
            response = self.client.table(table_name).select("*").in_(field_name, values).execute()
            
            # Group results by field value
            existing_records = {}
            for record in response.data:
                field_value = record.get(field_name)
                if field_value:
                    existing_records[field_value] = record
            
            return existing_records
            
        except Exception as e:
            logger.error(f"❌ Error getting existing records from {table_name}: {e}")
            return {}
        
    def update_data(self, data: dict, table_name: str):
        """Update data in the database"""
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return None
        
        try:
            response = self.client.table(table_name).update(data).execute()
            return response
        except Exception as e:
            logger.error(f"❌ Error updating data in {table_name}: {e}")
            return None

    def check_table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database
        
        Args:
            table_name (str): Name of the table to check
            
        Returns:
            bool: True if table exists, False otherwise
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return False
            
        try:
            # Try to query the table with a limit of 0 to check existence
            response = self.client.table(table_name).select("*").limit(0).execute()
            return True
        except Exception as e:
            logger.info(f"❌ Table {table_name} does not exist: {e}")
            return False

    def create_table_from_columns(self, column_names: List[str], table_name: str, unique_key: str) -> dict:
        """
        Create a table with TEXT columns from a list of column names
        
        Args:
            column_names (List[str]): List of column names to create
            table_name (str): Name of the table to create
            unique_key (str): Name of the primary key column (default: "id")
            
        Returns:
            dict: Result with status and SQL to execute
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {"status": "error", "message": "Database client not initialized"}
        
        try:
            # Build column definitions
            columns = []
            
            # Always add fixed "id" as primary key
            columns.append("id TEXT PRIMARY KEY")
            
            # Add all provided columns as TEXT
            for column_name in column_names:
                if column_name == "id":
                    continue  # Skip id since we already added it as primary key
                elif column_name == unique_key:
                    columns.append(f"{column_name} TEXT UNIQUE")  # Make unique_key a unique constraint
                else:
                    columns.append(f"{column_name} TEXT")
            
            # Add timestamp columns
            columns.append("created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
            columns.append("updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
            
            # Create SQL statement
            columns_sql = ",\n    ".join(columns)
            create_table_sql = f"""CREATE TABLE {table_name} ({columns_sql});""".strip()
            
            logger.info(f"Generated SQL for table {table_name}:\n{create_table_sql}")
            
            return {
                "status": "sql_generated",
                "message": f"SQL for creating table {table_name} has been generated. Please execute it manually in Supabase dashboard.",
                "table_name": table_name,
                "sql": create_table_sql,
                "columns": column_names,
                "primary_key": "id",
                "unique_key": unique_key
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating table from columns: {e}")
            return {"status": "error", "message": str(e)}

    def execute_sql_query(self, sql_query: str) -> dict:
        """
        Execute a SQL query directly using Supabase RPC
        
        Args:
            sql_query (str): SQL query to execute
            
        Returns:
            dict: Result with status and details
        """
        if not self.client:
            logger.error("❌ WARNING: Supabase client not initialized.")
            return {"status": "error", "message": "Database client not initialized"}
        
        try:
            # Use Supabase RPC to execute raw SQL
            # Note: This requires a database function to be created in Supabase
            # response = self.client.rpc('execute_sql', {'sql_query': sql_command}).execute()
            response = self.client.rpc('execute_sql_query', {'query': sql_query}).execute()
            
            if response.data:
                logger.info(f"SQL executed successfully: {sql_query[:100]}...")
                return {
                    "status": "success",
                    "message": "SQL query executed successfully",
                    "data": response.data
                }
            else:
                logger.warning("SQL executed but no data returned")
                return {
                    "status": "success",
                    "message": "SQL query executed successfully (no data returned)"
                }
                
        except Exception as e:
            logger.error(f"❌ Error executing SQL query: {e}")
            # If RPC method doesn't exist, provide alternative
            if "function execute_sql" in str(e).lower():
                return {
                    "status": "rpc_not_available",
                    "message": "Direct SQL execution not available. Please execute the SQL manually in Supabase dashboard.",
                    "sql_to_execute": sql_query,
                    "setup_instructions": """
                To enable direct SQL execution, create this function in your Supabase SQL editor:

                CREATE OR REPLACE FUNCTION execute_sql_query(sql_query text)
                RETURNS json
                LANGUAGE plpgsql
                SECURITY DEFINER
                AS $$
                BEGIN
                EXECUTE sql_query;
                RETURN '{"status": "success"}'::json;
                EXCEPTION WHEN OTHERS THEN
                RETURN json_build_object('error', SQLERRM);
                END;
                $$;
                    """
                }
            else:
                return {"status": "error", "message": str(e)}

    def run_sql(self, query: str) -> dict:
        """
        Execute any SQL query using Supabase RPC
        
        Args:
            query (str): SQL query to execute
            
        Returns:
            dict: {"status": "success/error", "data": [...], "message": "..."}
        """
        if not self.client:
            return {"status": "error", "message": "Database not connected", "data": []}
        
        try:
            # Call the database function we created
            response = self.client.rpc('execute_query', {'sql_text': query}).execute()
            
            # Check if there's an error in the response
            if isinstance(response.data, dict) and 'error' in response.data:
                return {
                    "status": "error",
                    "message": response.data.get('error', 'Unknown database error'),
                    "data": []
                }
            
            # Success case
            return {
                "status": "success",
                "message": f"Query executed successfully",
                "data": response.data or []
            }
            
        except Exception as e:
            error_msg = str(e)
            
            # Check if function doesn't exist
            if "execute_query" in error_msg and "not found" in error_msg.lower():
                return {
                    "status": "setup_required",
                    "message": "Database function not found. Please create it first.",
                    "data": [],
                    "setup_sql": """
CREATE OR REPLACE FUNCTION execute_query(sql_text text)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result json;
BEGIN
    EXECUTE format('SELECT json_agg(t) FROM (%s) t', sql_text) INTO result;
    RETURN COALESCE(result, '[]'::json);
EXCEPTION WHEN OTHERS THEN
    RETURN json_build_object('error', SQLERRM, 'code', SQLSTATE);
END;
$$;
                    """
                }
            
            return {"status": "error", "message": error_msg, "data": []}


database_service = DatabaseService()