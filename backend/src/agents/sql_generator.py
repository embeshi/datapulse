# src/agents/sql_generator.py
import logging
import re
from src.llm import client, prompts

logger = logging.getLogger(__name__)

def _extract_sql(raw_response: str) -> str:
    """Extracts SQL code, potentially removing markdown code fences."""
    logger.debug(f"Raw SQL Gen response: {raw_response}")
    # Regex to find ```sql ... ``` or ``` ... ``` blocks
    match = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw_response, re.DOTALL | re.IGNORECASE)
    if match:
        sql_query = match.group(1).strip()
        logger.info("Extracted SQL from markdown block.")
        return sql_query
    else:
        # If no markdown block, assume the whole response is the SQL (or contains it)
        # Basic cleanup: remove potential introductory/closing remarks if simple
        lines = raw_response.strip().splitlines()
        # Remove potential leading/trailing explanation lines if they don't look like SQL
        if lines and not lines[0].upper().strip().startswith(("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "PRAGMA")):
             lines = lines[1:]
        if lines and not lines[-1].strip().endswith(";"): # Very basic check
             # Heuristic: If last line doesn't end like SQL, maybe it's explanation?
             # This is risky, could remove valid SQL. Better prompts are key.
             # Consider removing this heuristic if it causes issues.
             pass # Decide if you want to trim trailing lines aggressively
        sql_query = "\n".join(lines).strip()
        if not sql_query:
             logger.warning("SQL Extraction failed, returning raw response.")
             return raw_response # Return raw if extraction uncertain
        logger.info("Returning cleaned raw response as SQL (no markdown block detected).")
        return sql_query


def _validate_table_references(sql_query: str, database_context: str) -> tuple[bool, str]:
    """
    Validates that all tables referenced in the SQL query exist in the database context.
    
    Args:
        sql_query: The SQL query string to validate
        database_context: String containing database schema and summaries
        
    Returns:
        Tuple of (is_valid, message) where is_valid is True if all tables exist,
        and message contains error details if invalid
    """
    # Extract table names from database_context (simple approach)
    existing_tables = []
    for line in database_context.splitlines():
        # Check for both the new and old table format
        if "--- Table:" in line:
            # New format: --- Table: tablename (Model: ModelName) ---
            table_match = re.search(r"--- Table: (\w+) \(Model:", line)
            if table_match:
                existing_tables.append(table_match.group(1).lower())
        elif "-- Table:" in line:
            # Old format: -- Table: tablename --
            table_match = re.search(r"-- Table: (\w+) --", line)
            if table_match:
                existing_tables.append(table_match.group(1).lower())
    
    # Extract table names from SQL query (simple approach)
    # This is a simplified implementation and might not catch all SQL variations
    sql_lower = sql_query.lower()
    # Look for FROM and JOIN clauses
    from_matches = re.findall(r"from\s+([a-zA-Z0-9_]+)", sql_lower)
    join_matches = re.findall(r"join\s+([a-zA-Z0-9_]+)", sql_lower)
    
    referenced_tables = set(from_matches + join_matches)
    
    # Log the tables we found for debugging
    logger.debug(f"Tables found in context: {existing_tables}")
    logger.debug(f"Tables referenced in query: {referenced_tables}")
    
    # Check if all referenced tables exist
    missing_tables = [table for table in referenced_tables if table not in existing_tables]
    
    if missing_tables:
        logger.warning(f"Tables not found: {missing_tables}. Context tables: {existing_tables}")
        return False, f"Referenced tables that don't exist: {', '.join(missing_tables)}"
    
    return True, "All table references are valid"

def run_sql_generator(conceptual_plan: str, database_context: str) -> str:
    """Generates the SQL query using the LLM."""
    logger.info(f"Running SQL generator for plan:\n{conceptual_plan}")
    try:
        prompt = prompts.get_sql_generation_prompt(conceptual_plan, database_context)
        raw_sql_response = client.call_llm(prompt)
        sql_query = _extract_sql(raw_sql_response)
        
        # Validate SQL references only existing tables
        is_valid, message = _validate_table_references(sql_query, database_context)
        if not is_valid:
            logger.warning(f"SQL validation failed: {message}")
            # If the SQL contains an error comment from our updated prompt, just return it
            if sql_query.strip().startswith('--'):
                return sql_query
            # Otherwise append our own error comment
            return f"-- ERROR: {message}\n-- Generated query may not execute successfully.\n{sql_query}"
        
        logger.info(f"SQL Generator produced query:\n{sql_query}")
        return sql_query
    except Exception as e:
        logger.error(f"SQL Generator agent failed: {e}")
        raise

def debug_sql_error(user_request: str, failed_sql: str, error_message: str, 
                    conceptual_plan: str, database_context: str) -> str:
    """
    Analyzes a failed SQL query, the error message, and suggests a corrected SQL query.
    
    Args:
        user_request: The original user query that initiated the analysis
        failed_sql: The SQL query that failed execution
        error_message: The database error message received
        conceptual_plan: The original conceptual plan that led to the SQL
        database_context: String containing schema and data summaries
        
    Returns:
        A suggested fixed SQL query
    """
    logger.info(f"Running SQL debugger for failed query with error: {error_message}")
    try:
        prompt = prompts.get_sql_debug_prompt(
            user_request, failed_sql, error_message, conceptual_plan, database_context
        )
        raw_debug_response = client.call_llm(prompt)
        fixed_sql = _extract_sql(raw_debug_response)
        
        # Validate the fixed SQL query references only existing tables
        is_valid, message = _validate_table_references(fixed_sql, database_context)
        if not is_valid:
            logger.warning(f"Fixed SQL still has validation issues: {message}")
            return f"-- WARNING: The suggested fix still has validation issues: {message}\n-- Use with caution.\n{fixed_sql}"
        
        logger.info(f"SQL Debugger produced fixed query:\n{fixed_sql}")
        return fixed_sql
    except Exception as e:
        logger.error(f"SQL Debugger agent failed: {e}")
        # In case of failure in the debugger itself, return something reasonable
        return f"-- ERROR: Could not generate a fix due to: {e}\n-- Original query with error: {error_message}\n{failed_sql}"
