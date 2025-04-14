import pytest
import sqlalchemy
from pathlib import Path
from src.data_handling.loader import load_csv_to_sqlite # Assuming loader is needed for setup
from src.data_handling.db_utils import get_sqlalchemy_engine

# Define test data path relative to the conftest file location
TEST_DATA_DIR = Path(__file__).parent.parent / "data" # Assumes data dir is sibling to tests
TEST_DB_PATH = Path(__file__).parent / "test_analysis.db" # Temporary DB for tests

@pytest.fixture(scope="session") # Run once per test session
def test_db_engine():
    """Fixture to set up and tear down a test SQLite database."""
    db_uri = f"sqlite:///{TEST_DB_PATH.resolve()}"

    # Ensure clean state before tests
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    # Create dummy data and load it (adjust paths/data as needed)
    dummy_csv = TEST_DATA_DIR / "sample_sales.csv" # Or create dummy data directly here
    if not dummy_csv.exists():
       pytest.skip(f"Test data CSV not found at {dummy_csv}") # Skip if data missing

    try:
        # Use your loader function to populate the test DB
        load_csv_to_sqlite(dummy_csv, db_uri, 'sales')
    except Exception as e:
        pytest.fail(f"Failed to set up test database: {e}")

    engine = get_sqlalchemy_engine(db_uri)
    yield engine # Provide the engine to tests

    # Teardown: Close connections if needed (usually handled by SQLAlchemy)
    # and remove the test database file
    engine.dispose() # Good practice to dispose engine
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()