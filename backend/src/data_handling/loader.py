import pandas as pd
import sqlalchemy
from pathlib import Path
from typing import Union
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_csv_to_sqlite(csv_path: Union[str, Path], db_uri: str, table_name: str) -> None:
    """
    Loads data from a CSV file into a specified table in a SQLite database.
    If the table exists, it will be replaced.

    Args:
        csv_path (Union[str, Path]): The path to the input CSV file.
        db_uri (str): The SQLAlchemy database URI (e.g., 'sqlite:///analysis.db').
        table_name (str): The name of the table to create/replace in the database.

    Raises:
        FileNotFoundError: If the csv_path does not exist.
        pd.errors.EmptyDataError: If the CSV file is empty.
        Exception: For other pandas or SQLAlchemy errors during loading/writing.
    """
    csv_filepath = Path(csv_path)
    if not csv_filepath.is_file():
        logger.error(f"CSV file not found at: {csv_path}")
        raise FileNotFoundError(f"CSV file not found at: {csv_path}")

    logger.info(f"Attempting to load CSV: {csv_path}")
    try:
        df = pd.read_csv(csv_filepath)
        if df.empty:
             logger.warning(f"CSV file is empty: {csv_path}")
             # Decide if empty CSV should create empty table or raise error
             # raise pd.errors.EmptyDataError(f"CSV file is empty: {csv_path}") # Option to raise

    except pd.errors.EmptyDataError as e:
         logger.error(f"Pandas EmptyDataError reading {csv_path}: {e}")
         raise
    except Exception as e:
        logger.error(f"Error reading CSV file {csv_path}: {e}")
        raise

    logger.info(f"Attempting to connect to database: {db_uri}")
    try:
        engine = sqlalchemy.create_engine(db_uri)
        logger.info(f"Writing data to table '{table_name}' (if_exists='replace')...")
        # Use DataFrame.to_sql for simplicity in loading
        df.to_sql(name=table_name, con=engine, if_exists='replace', index=False)
        logger.info(f"Successfully loaded data from {csv_path} to table '{table_name}' in {db_uri}")
    except sqlalchemy.exc.SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError writing to database {db_uri}, table '{table_name}': {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error writing to database: {e}")
        raise

# Example Usage (for direct testing)
if __name__ == "__main__":
    # Assume analysis.db will be created in the current working directory
    # and sample_data.csv is in a 'data' subdirectory relative to cwd
    DB_URI = 'sqlite:///analysis.db'
    SAMPLE_CSV = Path('data/sample_sales.csv') # Adjust path as needed
    TABLE_NAME = 'sales'

    # Create dummy data if file doesn't exist for testing
    if not SAMPLE_CSV.parent.exists():
        SAMPLE_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not SAMPLE_CSV.exists():
         logger.info(f"Creating dummy CSV data at {SAMPLE_CSV} for testing.")
         dummy_df = pd.DataFrame({
             'sale_id': [1, 2, 3, 4],
             'product_id': [101, 102, 101, 103],
             'amount': [10.50, 25.00, 12.00, 5.75],
             'sale_date': ['2025-04-10', '2025-04-11', '2025-04-11', '2025-04-12']
         })
         dummy_df.to_csv(SAMPLE_CSV, index=False)

    try:
        load_csv_to_sqlite(SAMPLE_CSV, DB_URI, TABLE_NAME)
        logger.info("Test load complete.")
    except Exception as e:
        logger.error(f"Test load failed: {e}")