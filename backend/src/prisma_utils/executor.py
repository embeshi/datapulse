import logging
import traceback
from typing import List, Dict, Any, Tuple, Optional
import json
import asyncio
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Determine if prisma-client-py is available
try:
    from prisma import Prisma
    PRISMA_AVAILABLE = True
except ImportError:
    logger.warning("prisma-client-py not found. Install with: pip install prisma")
    PRISMA_AVAILABLE = False

def _process_prisma_results(raw_results: List[Dict]) -> List[Dict[str, Any]]:
    """
    Process raw results from Prisma query to ensure JSON serializable.
    
    Args:
        raw_results: List of dictionaries from Prisma raw query
        
    Returns:
        Processed results list
    """
    processed_results = []
    
    for row in raw_results:
        processed_row = {}
        
        for key, value in row.items():
            # Handle datetime objects
            if hasattr(value, 'isoformat'):
                processed_row[key] = value.isoformat()
            # Handle other non-serializable types if needed
            elif isinstance(value, (bytes, bytearray)):
                processed_row[key] = value.hex()
            else:
                processed_row[key] = value
                
        processed_results.append(processed_row)
        
    return processed_results

async def execute_prisma_raw_sql_async(sql_query: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Executes a raw SQL query using Prisma client async interface.
    
    Args:
        sql_query: SQL query string to execute
        
    Returns:
        Tuple containing:
        - List of result rows as dictionaries (if query returns rows and succeeds)
        - None (if execution succeeds)
        OR
        - Empty List
        - Error message string (if execution fails)
    """
    if not PRISMA_AVAILABLE:
        return [], "Error: prisma-client-py not installed. Install with: pip install prisma"
    
    logger.info(f"Executing SQL query via Prisma: {sql_query[:100]}...")
    
    prisma = Prisma()
    try:
        await prisma.connect()
        
        # Execute the raw query
        result = await prisma.query_raw(sql_query)
        
        # Process results to ensure they're JSON serializable
        processed_results = _process_prisma_results(result)
        
        logger.info(f"Query executed successfully, {len(processed_results)} rows returned.")
        return processed_results, None
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error executing query: {error_msg}")
        return [], error_msg
        
    finally:
        try:
            await prisma.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting from Prisma: {e}")

def execute_prisma_raw_sql_sync(sql_query: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Synchronous wrapper around the async Prisma executor.
    
    Args:
        sql_query: SQL query string to execute
        
    Returns:
        Same as execute_prisma_raw_sql_async
    """
    if not PRISMA_AVAILABLE:
        return [], "Error: prisma-client-py not installed. Install with: pip install prisma"
    
    logger.info(f"Executing SQL query via Prisma (sync): {sql_query[:100]}...")
    
    try:
        # Check if we're already in an event loop
        try:
            loop = asyncio.get_running_loop()
            # We're already in an event loop - use SQLite CLI fallback
            logger.warning("Already in an event loop, using SQLite CLI fallback")
            return execute_sqlite_cli_sql(sql_query)
        except RuntimeError:
            # No running event loop, we can create one safely
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results, error = loop.run_until_complete(execute_prisma_raw_sql_async(sql_query))
                return results, error
            finally:
                loop.close()
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error executing query (sync wrapper): {error_msg}")
        # Try the fallback if the main execution fails
        logger.info("Attempting fallback to SQLite CLI execution")
        try:
            return execute_sqlite_cli_sql(sql_query)
        except Exception as fallback_e:
            logger.error(f"Fallback execution also failed: {fallback_e}")
            return [], f"{error_msg} (Fallback also failed: {fallback_e})"

# Fallback using sqlite3 command-line if prisma isn't working
def execute_sqlite_cli_sql(sql_query: str, db_path: str = "analysis.db") -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Fallback executor using sqlite3 command-line tool.
    
    Args:
        sql_query: SQL query string to execute
        db_path: Path to SQLite database file
        
    Returns:
        Same format as execute_prisma_raw_sql_async
    """
    logger.info(f"Executing SQL query via sqlite3 CLI: {sql_query[:100]}...")
    
    try:
        # Check if database file exists
        if not Path(db_path).exists():
            return [], f"Error: Database file {db_path} not found"
        
        # Create temp file for SQL
        sql_file = Path("temp_query.sql")
        sql_file.write_text(sql_query)
        
        # Execute SQL using sqlite3 CLI with JSON output
        result = subprocess.run(
            ["sqlite3", db_path, "-json", f".read {sql_file}"],
            capture_output=True,
            text=True,
            check=False
        )
        
        # Clean up temp file
        sql_file.unlink()
        
        if result.returncode != 0:
            logger.error(f"SQLite CLI error: {result.stderr}")
            return [], f"SQLite error: {result.stderr}"
        
        # Parse JSON output
        try:
            if result.stdout.strip():
                rows = json.loads(result.stdout)
                logger.info(f"Query executed successfully, {len(rows)} rows returned via SQLite CLI.")
                return rows, None
            else:
                # Non-SELECT queries return empty output but may have succeeded
                logger.info("Query executed, no rows returned (likely non-SELECT query).")
                return [], None
        except json.JSONDecodeError:
            logger.error(f"Could not parse SQLite JSON output: {result.stdout}")
            return [], "Error parsing SQLite output"
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error executing query via SQLite CLI: {error_msg}")
        return [], f"SQLite CLI error: {error_msg}"

# Example usage for testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example queries
    TEST_SELECT_QUERY = "SELECT * FROM sales LIMIT 5"
    TEST_ERROR_QUERY = "SELECT * FROM nonexistent_table"
    
    logger.info("\n--- Testing Prisma SQL Executor ---")
    
    if PRISMA_AVAILABLE:
        # Test async executor
        async def test_async():
            logger.info("\n[Test 1: Async Valid Query]")
            results, error = await execute_prisma_raw_sql_async(TEST_SELECT_QUERY)
            if error:
                logger.error(f"Test 1 failed: {error}")
            else:
                logger.info(f"Test 1 succeeded: {len(results)} rows returned")
                print(f"Sample results: {results[:2]}")
            
            logger.info("\n[Test 2: Async Error Query]")
            results, error = await execute_prisma_raw_sql_async(TEST_ERROR_QUERY)
            if error:
                logger.info(f"Test 2 correctly returned error: {error}")
            else:
                logger.error(f"Test 2 should have failed but returned {len(results)} rows")
        
        # Run async tests
        asyncio.run(test_async())
        
        # Test sync wrapper
        logger.info("\n[Test 3: Sync Valid Query]")
        results, error = execute_prisma_raw_sql_sync(TEST_SELECT_QUERY)
        if error:
            logger.error(f"Test 3 failed: {error}")
        else:
            logger.info(f"Test 3 succeeded: {len(results)} rows returned")
            print(f"Sample results: {results[:2]}")
    else:
        logger.warning("Skipping Prisma tests - prisma-client-py not installed")
        
    # Test SQLite CLI fallback
    logger.info("\n[Test 4: SQLite CLI Valid Query]")
    results, error = execute_sqlite_cli_sql(TEST_SELECT_QUERY)
    if error:
        logger.error(f"Test 4 failed: {error}")
    else:
        logger.info(f"Test 4 succeeded: {len(results)} rows returned")
        print(f"Sample results: {results[:2]}")
