import sqlalchemy
from sqlalchemy import inspect, text, func, select, column, literal_column, cast, String
from typing import List, Dict, Tuple, Optional, Any
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# Max distinct values to fetch for value_counts summary
MAX_DISTINCT_VALUES_FOR_SUMMARY = 10

def get_table_summary(engine: sqlalchemy.engine.Engine, table_name: str, columns_info: List[Dict]) -> Dict[str, Any]:
    """
    Generates a summary dictionary for a given table using SQL queries.

    Args:
        engine: SQLAlchemy engine instance.
        table_name: Name of the table to summarize.
        columns_info: List of column dictionaries from inspector.get_columns().

    Returns:
        Dictionary containing summary statistics (row_count, null_counts, distinct_counts, basic_stats).
    """
    summary = {
        "row_count": 0,
        "null_counts": {},
        "distinct_counts": {},
        "basic_stats": {}, # For numerical columns (min, max, avg)
        "value_counts": {} # For low-cardinality text/categorical columns
    }
    logger.info(f"Generating summary for table: {table_name}")

    try:
        with engine.connect() as connection:
            # Get row count
            count_query = f"SELECT COUNT(*) FROM \"{table_name}\"" # Use quotes for safety
            result = connection.execute(text(count_query))
            summary["row_count"] = result.scalar_one_or_none() or 0

            if summary["row_count"] == 0:
                logger.info(f"Table '{table_name}' is empty, skipping detailed summaries.")
                return summary # No point summarizing empty table

            # Get summaries per column
            for col_info in columns_info:
                col_name = col_info['name']
                col_type = col_info['type']
                col_name_quoted = f"\"{col_name}\"" # Quote column names

                try:
                    # Null counts
                    null_query = f"SELECT SUM(CASE WHEN {col_name_quoted} IS NULL THEN 1 ELSE 0 END) FROM \"{table_name}\""
                    null_count = connection.execute(text(null_query)).scalar_one_or_none() or 0
                    summary["null_counts"][col_name] = null_count

                    # Distinct counts
                    distinct_query = f"SELECT COUNT(DISTINCT {col_name_quoted}) FROM \"{table_name}\""
                    distinct_count = connection.execute(text(distinct_query)).scalar_one_or_none() or 0
                    summary["distinct_counts"][col_name] = distinct_count

                    # Basic stats for numeric types (simplistic check)
                    # In a real system, use reflection to get precise numeric types
                    is_numeric = isinstance(col_type, (sqlalchemy.types.Integer, sqlalchemy.types.Float, sqlalchemy.types.Numeric))
                    if is_numeric:
                        stats_query = f"SELECT MIN({col_name_quoted}), MAX({col_name_quoted}), AVG({col_name_quoted}) FROM \"{table_name}\""
                        min_val, max_val, avg_val = connection.execute(text(stats_query)).first() or (None, None, None)
                        summary["basic_stats"][col_name] = {"min": min_val, "max": max_val, "avg": avg_val}

                    # Value counts for low cardinality text/categorical columns
                    # Using distinct count as a proxy for cardinality check
                    is_text_like = isinstance(col_type, (sqlalchemy.types.String, sqlalchemy.types.Text, sqlalchemy.types.Enum)) # Add others if needed
                    if is_text_like and distinct_count <= MAX_DISTINCT_VALUES_FOR_SUMMARY:
                        # Need to handle potential nulls in group by and cast for safety
                        vc_query = f"""
                            SELECT CAST({col_name_quoted} AS VARCHAR) as value, COUNT(*) as count
                            FROM \"{table_name}\"
                            GROUP BY CAST({col_name_quoted} AS VARCHAR)
                            ORDER BY count DESC
                            LIMIT {MAX_DISTINCT_VALUES_FOR_SUMMARY}
                        """
                        vc_result = connection.execute(text(vc_query)).mappings().all()
                        summary["value_counts"][col_name] = {row['value'] if row['value'] is not None else 'NULL': row['count'] for row in vc_result}

                except sqlalchemy.exc.SQLAlchemyError as col_err:
                     logger.warning(f"Could not generate summary for column '{col_name}' in table '{table_name}': {col_err}")
                     summary["null_counts"][col_name] = "Error"
                     summary["distinct_counts"][col_name] = "Error"
                     if is_numeric: summary["basic_stats"][col_name] = "Error"
                     if is_text_like: summary["value_counts"][col_name] = "Error"
                except Exception as col_err_unexp:
                     logger.error(f"Unexpected error summarizing column '{col_name}': {col_err_unexp}")
                     # Add error indicators to prevent downstream issues
                     summary["null_counts"][col_name] = "Error"
                     summary["distinct_counts"][col_name] = "Error"


    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError generating summary for table '{table_name}': {e}")
        # Indicate summary failure
        return {"error": f"Failed to summarize table {table_name}: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error generating summary for '{table_name}': {e}")
        logger.error(traceback.format_exc())
        return {"error": f"Unexpected error summarizing table {table_name}."}

    logger.info(f"Successfully generated summary for table: {table_name}")
    return summary


def get_database_context_string(engine: sqlalchemy.engine.Engine) -> str:
    """
    Introspects the database and generates a combined string containing
    schema information and basic data summaries for each table.

    Args:
        engine: SQLAlchemy engine instance.

    Returns:
        String containing formatted schema and summaries.
    """
    logger.info("Introspecting database schema and generating summaries...")
    try:
        inspector = inspect(engine)
        context_parts = []
        table_names = inspector.get_table_names()

        if not table_names:
            logger.warning("No tables found in the database.")
            return "Database Context: No tables found."

        context_parts.append("Database Context:")
        for table_name in table_names:
            context_parts.append(f"\n-- Table: {table_name} --")
            columns = inspector.get_columns(table_name)
            if not columns:
                 context_parts.append("  (No columns found or introspection error)")
                 continue

            # Schema part
            cols_str = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
            context_parts.append(f"  Schema Columns: {cols_str}")

            # Summary part
            summary = get_table_summary(engine, table_name, columns)
            context_parts.append(f"  Summary:")
            if summary.get("error"):
                context_parts.append(f"    Error: {summary['error']}")
            else:
                context_parts.append(f"    Total Rows: {summary.get('row_count', 'N/A')}")
                if summary.get("row_count", 0) > 0: # Only show details if table not empty
                    context_parts.append(f"    Null Counts: {summary.get('null_counts', {})}")
                    context_parts.append(f"    Distinct Counts: {summary.get('distinct_counts', {})}")
                    if summary.get('basic_stats'):
                        context_parts.append(f"    Basic Stats (Numeric): {summary.get('basic_stats', {})}")
                    if summary.get('value_counts'):
                         context_parts.append(f"    Top Value Counts (Low Cardinality Text): {summary.get('value_counts', {})}")

        context_string = "\n".join(context_parts).strip()
        logger.info("Database context string generated successfully.")
        return context_string

    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError during context generation: {e}")
        return f"Error: Could not generate database context. {e}"
    except Exception as e:
        logger.error(f"Unexpected error during context generation: {e}")
        logger.error(traceback.format_exc())
        return "Error: An unexpected error occurred during context generation."
    

def get_sqlalchemy_engine(db_uri: str) -> sqlalchemy.engine.Engine:
    """
    Creates and returns a SQLAlchemy engine instance.

    Args:
        db_uri (str): The SQLAlchemy database URI (e.g., 'sqlite:///analysis.db').

    Returns:
        sqlalchemy.engine.Engine: The SQLAlchemy engine instance.

    Raises:
        ImportError: If the required DB driver is not installed.
        ArgumentError: If the db_uri is invalid.
    """
    try:
        engine = sqlalchemy.create_engine(db_uri)
        # Optional: Test connection immediately?
        # with engine.connect() as connection:
        #     logger.info(f"Successfully created engine and connected to {db_uri}")
        return engine
    except ImportError as e:
         logger.error(f"DB driver not found for URI '{db_uri}'. Install required driver (e.g., pysqlite typically included): {e}")
         raise
    except sqlalchemy.exc.ArgumentError as e:
         logger.error(f"Invalid database URI format '{db_uri}': {e}")
         raise
    except Exception as e:
        logger.error(f"Failed to create SQLAlchemy engine for '{db_uri}': {e}")
        raise


def execute_sql(engine: sqlalchemy.engine.Engine, sql_query: str) -> Tuple[List[Dict], Optional[str]]:
    """
    Executes a given SQL query string against the database using the provided engine.

    Args:
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine to use.
        sql_query (str): The SQL query string to execute.

    Returns:
        Tuple[List[Dict], Optional[str]]: A tuple containing:
            - List of result rows as dictionaries (if query returns rows and succeeds).
            - None (if execution succeeds).
        OR
            - Empty List.
            - Error message string (if execution fails).
    """
    logger.info(f"Executing SQL query: {sql_query[:100]}...") # Log truncated query
    try:
        with engine.connect() as connection:
            # Use text() for literal SQL execution
            result_proxy = connection.execute(text(sql_query))
            # Check if the statement returns rows (e.g., SELECT)
            if result_proxy.returns_rows:
                 # Fetch all results as dictionaries
                 results = [dict(row) for row in result_proxy.mappings().all()]
                 logger.info(f"Query executed successfully, {len(results)} rows returned.")
                 return results, None
            else:
                 # For statements like INSERT, UPDATE, DELETE that don't return rows
                 # result_proxy.rowcount might be useful depending on dialect
                 logger.info(f"Query executed successfully (no rows returned). Row count: {result_proxy.rowcount}")
                 return [], None
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError executing query: {e}")
        return [], str(e)
    except Exception as e:
        logger.error(f"Unexpected error executing query: {e}")
        return [], str(e)


def get_db_schema_string(engine: sqlalchemy.engine.Engine) -> str:
    """
    Introspects the database using the provided engine and returns a
    formatted string describing the schema (tables and columns/types).

    Args:
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine to use.

    Returns:
        str: A formatted string describing the database schema.
    """
    logger.info("Introspecting database schema...")
    try:
        inspector = inspect(engine)
        schema_parts = []
        table_names = inspector.get_table_names()

        if not table_names:
            logger.warning("No tables found in the database.")
            return "Schema: No tables found in the database."

        for table_name in table_names:
            schema_parts.append(f"Table: {table_name}")
            columns = inspector.get_columns(table_name)
            # Format columns: name (TYPE), name (TYPE), ...
            cols_str = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
            schema_parts.append(f"  Columns: {cols_str}")
            schema_parts.append("") # Add a blank line between tables

        schema_string = "Database Schema:\n" + "\n".join(schema_parts).strip()
        logger.info("Schema introspection successful.")
        return schema_string
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError during schema introspection: {e}")
        return f"Error: Could not introspect database schema. {e}"
    except Exception as e:
        logger.error(f"Unexpected error during schema introspection: {e}")
        return f"Error: An unexpected error occurred during schema introspection. {e}"


# Example Usage (for direct testing)
if __name__ == "__main__":
    DB_URI = 'sqlite:///analysis.db' # Assumes analysis.db exists from loader test

    try:
        logger.info(f"\n--- Testing DB Utils with URI: {DB_URI} ---")
        engine = get_sqlalchemy_engine(DB_URI)

        # 1. Test Schema Introspection
        logger.info("\n[Test 1: Get Schema]")
        schema = get_db_schema_string(engine)
        print("--- Schema ---")
        print(schema)
        print("--------------")

        # 2. Test SQL Execution (SELECT)
        logger.info("\n[Test 2: Execute SELECT Query]")
        # Use table name from loader example
        select_query = "SELECT * FROM sales LIMIT 3;"
        results, error = execute_sql(engine, select_query)
        if error:
            logger.error(f"SELECT query failed: {error}")
        else:
            logger.info(f"SELECT query results:")
            for row in results:
                print(row)

        # 3. Test SQL Execution (Non-SELECT, e.g., PRAGMA)
        logger.info("\n[Test 3: Execute Non-SELECT Query (PRAGMA)]")
        pragma_query = "PRAGMA table_info(sales);" # Example non-data returning query
        results_pragma, error_pragma = execute_sql(engine, pragma_query)
        if error_pragma:
             logger.error(f"PRAGMA query failed: {error_pragma}")
        else:
             logger.info(f"PRAGMA query successful. Results (if any): {results_pragma}")

        # 4. Test SQL Execution (Error Case)
        logger.info("\n[Test 4: Execute Invalid Query]")
        invalid_query = "SELECT non_existent_column FROM sales;"
        results_invalid, error_invalid = execute_sql(engine, invalid_query)
        if error_invalid:
            logger.info(f"Invalid query failed as expected: {error_invalid}")
        else:
            logger.error(f"Invalid query somehow succeeded? Results: {results_invalid}")

        logger.info("\n--- DB Utils Tests Complete ---")

        # 5. Test Full Database Context Generation
        logger.info("\n[Test 5: Get Full Database Context]")
        context = get_database_context_string(engine)
        print("--- Database Context ---")
        print(context)
        print("----------------------")

        logger.info("\n--- DB Utils Tests Complete ---")

    except Exception as e:
        logger.error(f"Error during db_utils testing: {e}")
        logger.error(traceback.format_exc())
