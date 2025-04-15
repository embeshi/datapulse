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


def _validate_sql_query(sql_query: str, database_context: str) -> tuple[bool, str]:
    """
    Performs comprehensive validation of an SQL query against the database context.
    
    Args:
        sql_query: The SQL query string to validate
        database_context: String containing database schema and summaries
        
    Returns:
        Tuple of (is_valid, message) where is_valid is True if query is valid,
        and message contains error details if invalid
    """
    # First, validate table references
    is_tables_valid, tables_message = _validate_table_references(sql_query, database_context)
    if not is_tables_valid:
        return False, tables_message
    
    # Validate column references
    is_columns_valid, columns_message = _validate_column_references(sql_query, database_context)
    if not is_columns_valid:
        return False, columns_message
    
    # Validate basic SQL syntax
    is_syntax_valid, syntax_message = _validate_sql_syntax(sql_query)
    if not is_syntax_valid:
        return False, syntax_message
    
    # If we get here, validation passed
    return True, "SQL query validation passed"

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

def _validate_column_references(sql_query: str, database_context: str) -> tuple[bool, str]:
    """
    Validates that all columns referenced in the SQL query exist in the specified tables.
    
    Args:
        sql_query: The SQL query string to validate
        database_context: String containing database schema and summaries
        
    Returns:
        Tuple of (is_valid, message) where is_valid is True if all columns exist,
        and message contains error details if invalid
    """
    # Extract table-column mapping from database context
    tables_columns = {}
    current_table = None
    
    for line in database_context.splitlines():
        # Identify the current table being processed
        if "--- Table:" in line or "-- Table:" in line:
            # New format: --- Table: tablename (Model: ModelName) ---
            table_match = re.search(r"---? Table: (\w+)", line)
            if table_match:
                current_table = table_match.group(1).lower()
                tables_columns[current_table] = []
        
        # If we're processing a table and find column definitions
        elif current_table and (line.strip().startswith("- ") or line.strip().startswith("Schema Columns:")):
            # Try to extract column names from different formats
            if "Schema Columns:" in line:
                # Old format: "Schema Columns: col1 (type), col2 (type)..."
                cols_part = line.split("Schema Columns:")[1].strip()
                cols = re.findall(r'(\w+)\s*\([^)]*\)', cols_part)
                tables_columns[current_table].extend([c.lower() for c in cols])
            else:
                # New format: "- colname (type) [attributes]..."
                col_match = re.search(r'-\s+(\w+)\s+\(', line)
                if col_match:
                    tables_columns[current_table].append(col_match.group(1).lower())
                    
                # Also check for DB column names that differ from field names
                db_col_match = re.search(r'\[DB:\s+(\w+)\]', line)
                if db_col_match:
                    tables_columns[current_table].append(db_col_match.group(1).lower())
    
    # Parse the SQL to extract table aliases and column references
    sql_lower = sql_query.lower()
    
    # Extract table aliases (e.g., "FROM table AS t" or "FROM table t")
    alias_pattern = r'(?:from|join)\s+(\w+)(?:\s+as)?\s+(\w+)'
    aliases = dict(re.findall(alias_pattern, sql_lower))
    
    # Additional pattern to catch aliases without 'as'
    more_aliases = re.findall(r'from\s+(\w+)\s+(\w+)(?:\s|,|where|$)', sql_lower)
    for table, alias in more_aliases:
        if alias not in ['where', 'on', 'inner', 'outer', 'left', 'right', 'full', 'cross', 'join']:
            aliases[table] = alias
    
    # Extract column references with their table prefixes
    column_refs = []
    
    # Select clause columns
    select_match = re.search(r'select\s+(.*?)\s+from', sql_lower, re.DOTALL)
    if select_match:
        select_columns = select_match.group(1).strip()
        # Handle some common SQL functions and constructs
        for func in ['count', 'sum', 'avg', 'min', 'max', 'coalesce', 'case when']:
            select_columns = re.sub(f'{func}\s*\((.+?)\)', r'\1', select_columns)
        
        # Extract column references like "t.col", "table.col", or just "col"
        select_cols = re.findall(r'(?:^|,|\s)(?:(\w+)\.)?(\w+)(?:$|\s|,|as)', select_columns)
        column_refs.extend(select_cols)
    
    # Where clause columns
    where_match = re.search(r'where\s+(.*?)(?:$|group by|order by|limit)', sql_lower, re.DOTALL)
    if where_match:
        where_columns = where_match.group(1).strip()
        where_cols = re.findall(r'(\w+)\.(\w+)', where_columns)
        column_refs.extend(where_cols)
    
    # Order by columns
    order_match = re.search(r'order by\s+(.*?)(?:$|limit)', sql_lower, re.DOTALL)
    if order_match:
        order_columns = order_match.group(1).strip()
        order_cols = re.findall(r'(\w+)\.(\w+)', order_columns)
        column_refs.extend(order_cols)
    
    # Group by columns
    group_match = re.search(r'group by\s+(.*?)(?:$|having|order by|limit)', sql_lower, re.DOTALL)
    if group_match:
        group_columns = group_match.group(1).strip()
        group_cols = re.findall(r'(\w+)\.(\w+)', group_columns)
        column_refs.extend(group_cols)
    
    # Join conditions
    join_match = re.search(r'join.*?on\s+(.*?)(?:$|where|group by|order by|limit|join)', sql_lower, re.DOTALL)
    if join_match:
        join_columns = join_match.group(1).strip()
        join_cols = re.findall(r'(\w+)\.(\w+)', join_columns)
        column_refs.extend(join_cols)
    
    # Validate each column reference
    invalid_columns = []
    
    for table_ref, col in column_refs:
        # Skip if it's not a real column reference (e.g., * or 1)
        if col == '*' or col.isdigit() or col in ['true', 'false']:
            continue
            
        # Skip column aliases in the select list (heuristic)
        if col in aliases.values():
            continue
            
        # Find the actual table name from alias if used
        table_name = None
        if table_ref in aliases.values():
            # It's an alias, find the original table
            for orig_table, alias in aliases.items():
                if alias == table_ref:
                    table_name = orig_table
                    break
        elif table_ref in tables_columns:
            # Direct table reference
            table_name = table_ref
        elif not table_ref:
            # No table prefix (like in SELECT col)
            # This is harder - need to check all tables
            found = False
            for t, cols in tables_columns.items():
                if col in cols:
                    found = True
                    break
            if found:
                continue
            else:
                invalid_columns.append(f"Column '{col}' not found in any table")
                continue
        else:
            # Could be a table name not found in schema
            invalid_columns.append(f"Table or alias '{table_ref}' not found in schema")
            continue
            
        # Now check if the column exists in that table
        if table_name and table_name in tables_columns:
            if col not in tables_columns[table_name]:
                invalid_columns.append(f"Column '{col}' not found in table '{table_name}'")
    
    if invalid_columns:
        return False, f"Invalid column references: {', '.join(invalid_columns)}"
    
    return True, "All column references are valid"

def _validate_sql_syntax(sql_query: str) -> tuple[bool, str]:
    """
    Performs basic syntax validation on SQL query without executing it.
    
    Args:
        sql_query: The SQL query string to validate
        
    Returns:
        Tuple of (is_valid, message) where is_valid is True if syntax appears valid,
        and message contains error details if invalid
    """
    # Check for basic SQL syntax issues
    
    # 1. Verify all parentheses are balanced
    if sql_query.count('(') != sql_query.count(')'):
        return False, "Unbalanced parentheses in SQL query"
    
    # 2. Check for basic patterns of common SQL statements
    sql_lower = sql_query.lower().strip()
    
    # Check if it starts with basic SQL keywords
    valid_starts = ['select', 'with', 'create', 'insert', 'update', 'delete']
    if not any(sql_lower.startswith(keyword) for keyword in valid_starts):
        return False, "SQL query doesn't start with a valid SQL command"
    
    # 3. For SELECT statements, check for basic required syntax structure
    if sql_lower.startswith('select'):
        if 'from' not in sql_lower:
            return False, "SELECT query missing FROM clause"
    
    # 4. Check for unclosed quotes
    single_quotes = sql_query.count("'")
    double_quotes = sql_query.count('"')
    if single_quotes % 2 != 0:
        return False, "Unclosed single quotes in SQL query"
    if double_quotes % 2 != 0:
        return False, "Unclosed double quotes in SQL query"
    
    # 5. Check for missing semicolons in multi-statement queries
    statements = sql_lower.count(';')
    if statements > 1 and not sql_lower.endswith(';'):
        return False, "Multi-statement SQL query missing semicolon at the end"
    
    return True, "SQL syntax appears valid"

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
