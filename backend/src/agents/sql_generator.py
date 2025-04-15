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

def refine_sql_query(sql_query: str, validation_error: str, conceptual_plan: str, database_context: str) -> str:
    """
    Refines an SQL query based on validation errors by prompting the LLM.
    
    Args:
        sql_query: The original SQL query with errors
        validation_error: The error message from validation
        conceptual_plan: The original conceptual plan
        database_context: String containing database schema and summaries
        
    Returns:
        A refined SQL query addressing the validation errors
    """
    logger.info(f"Refining SQL query based on validation error: {validation_error}")
    
    try:
        # Generate a prompt for the LLM to refine the SQL
        prompt = prompts.get_sql_refinement_prompt(
            sql_query, validation_error, conceptual_plan, database_context
        )
        
        # Call the LLM with the refinement prompt
        raw_refined_sql = client.call_llm(prompt)
        
        # Extract the SQL from the response
        refined_sql = _extract_sql(raw_refined_sql)
        
        logger.info(f"SQL refinement produced updated query:\n{refined_sql}")
        return refined_sql
        
    except Exception as e:
        logger.error(f"SQL refinement failed: {e}")
        # If refinement fails, return the original query with an error comment
        return f"-- ERROR: Failed to refine query: {e}\n-- Original validation error: {validation_error}\n{sql_query}"

def run_sql_generator(conceptual_plan: str, database_context: str) -> str:
    """Generates the SQL query using the LLM, with automatic validation and refinement."""
    logger.info(f"Running SQL generator for plan:\n{conceptual_plan}")
    try:
        # Initial SQL generation
        prompt = prompts.get_sql_generation_prompt(conceptual_plan, database_context)
        raw_sql_response = client.call_llm(prompt)
        sql_query = _extract_sql(raw_sql_response)
        
        # Validate the SQL query
        is_valid, message = _validate_sql_query(sql_query, database_context)
        
        # If valid, return it directly
        if is_valid:
            logger.info(f"SQL validation passed. Final query:\n{sql_query}")
            return sql_query
        
        # If invalid and contains explicit error comment, just return it
        if sql_query.strip().startswith('--'):
            logger.warning(f"SQL contains explicit error marker: {sql_query[:100]}...")
            return sql_query
            
        # Attempt to refine the SQL query automatically
        logger.warning(f"SQL validation failed: {message}. Attempting automatic refinement.")
        
        # Maximum refinement attempts to prevent infinite loops
        max_attempts = 2
        current_attempt = 0
        current_query = sql_query
        
        while current_attempt < max_attempts:
            current_attempt += 1
            logger.info(f"SQL refinement attempt {current_attempt} of {max_attempts}")
            
            # Refine the SQL
            refined_sql = refine_sql_query(
                current_query, message, conceptual_plan, database_context
            )
            
            # Validate the refined SQL
            is_refined_valid, refined_message = _validate_sql_query(refined_sql, database_context)
            
            if is_refined_valid:
                logger.info(f"Refinement successful. Valid SQL query produced on attempt {current_attempt}")
                # Add a comment indicating this was auto-refined
                return f"-- NOTE: This query was automatically refined to fix validation issues\n{refined_sql}"
            
            # If still invalid but different error, keep trying
            if refined_message != message:
                logger.info(f"Progress in refinement: New error is: {refined_message}")
                current_query = refined_sql
                message = refined_message
            else:
                # Same error persists, break the loop
                logger.warning(f"Refinement not making progress, same error persists: {message}")
                break
        
        # If we've exhausted refinement attempts or stopped due to lack of progress
        if current_attempt > 0:
            logger.warning(f"SQL refinement unsuccessful after {current_attempt} attempts. Returning best attempt with warning.")
            return f"-- WARNING: Validation errors remain after {current_attempt} refinement attempts: {message}\n{current_query}"
        else:
            # We shouldn't reach this point, but as a fallback:
            logger.warning(f"SQL validation failed and refinement was not attempted: {message}")
            return f"-- ERROR: {message}\n-- Generated query may not execute successfully.\n{sql_query}"
        
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
