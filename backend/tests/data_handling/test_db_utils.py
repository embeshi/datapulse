import pytest
from src.data_handling.db_utils import execute_sql, get_db_schema_string
from sqlalchemy.engine import Engine # Import type hint

# The test_db_engine fixture is automatically injected by pytest
# because it's defined in conftest.py in the same or parent directory

def test_execute_sql_select_valid(test_db_engine: Engine):
    """Test executing a valid SELECT query."""
    sql = "SELECT sale_id FROM sales WHERE amount > 20;"
    results, error = execute_sql(test_db_engine, sql)
    assert error is None
    assert isinstance(results, list)
    assert len(results) >= 1 # Based on dummy data assumption
    assert 'sale_id' in results[0]
    assert results[0]['sale_id'] == 2 # Specific check based on dummy data

def test_execute_sql_invalid(test_db_engine: Engine):
    """Test executing an invalid SQL query."""
    sql = "SELECT non_existent_column FROM sales;"
    results, error = execute_sql(test_db_engine, sql)
    assert error is not None
    assert isinstance(error, str)
    assert "no such column" in error.lower()
    assert results == []

def test_get_db_schema_string(test_db_engine: Engine):
    """Test retrieving the database schema as a string."""
    schema_string = get_db_schema_string(test_db_engine)
    assert isinstance(schema_string, str)
    assert "Table: sales" in schema_string
    assert "sale_id (BIGINT)" in schema_string # Type might vary based on pandas/sqlite version
    assert "amount (FLOAT)" in schema_string

# Add more tests for edge cases, different SQL commands, etc.