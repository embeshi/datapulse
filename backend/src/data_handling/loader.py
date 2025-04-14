import pandas as pd
import sqlalchemy
from pathlib import Path
from typing import Union, Dict, List, Optional, Tuple, Any
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

        # Basic preprocessing: Convert pandas NaNs/NaTs to None for SQLite compatibility
        # This helps prevent errors if schema defines columns as non-nullable for types
        # where pandas uses specific sentinels (like NaT for datetime).
        df = df.astype(object).where(pd.notnull(df), None)

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
        logger.error(f"This often happens due to data type mismatches between CSV data and the database schema defined by Prisma.")
        logger.error(traceback.format_exc())
        raise Exception(f"Failed to load data into '{table_name}' due to DB error (check types/constraints).") from e
    except Exception as e:
        logger.error(f"Unexpected error writing to database: {e}")
        logger.error(traceback.format_exc())
        raise

def load_multiple_csvs_to_sqlite(
    csv_mapping: Dict[str, Union[str, Path]], 
    db_uri: str,
    infer_relationships: bool = False
) -> Dict[str, bool]:
    """
    Loads multiple CSV files into a SQLite database, with optional relationship inference.
    
    Args:
        csv_mapping (Dict[str, Union[str, Path]]): Dictionary mapping table names to CSV file paths
        db_uri (str): The SQLAlchemy database URI (e.g., 'sqlite:///analysis.db')
        infer_relationships (bool): Whether to attempt inferring relationships between tables based on column names
                                   (Not yet implemented)
    
    Returns:
        Dict[str, bool]: Dictionary mapping table names to success status
        
    Example:
        files_to_load = {
            'sales': 'data/sales.csv',
            'products': 'data/products.csv',
            'customers': 'data/customers.csv'
        }
        results = load_multiple_csvs_to_sqlite(files_to_load, 'sqlite:///analysis.db')
    """
    results = {}
    
    logger.info(f"Beginning batch load of {len(csv_mapping)} CSV files to {db_uri}")
    
    # First pass: Load all tables
    for table_name, csv_path in csv_mapping.items():
        try:
            load_csv_to_sqlite(csv_path, db_uri, table_name)
            results[table_name] = True
            logger.info(f"Successfully loaded {csv_path} to table '{table_name}'")
        except Exception as e:
            results[table_name] = False
            logger.error(f"Failed to load {csv_path} to table '{table_name}': {e}")
    
    # Optionally infer and create relationships
    if infer_relationships:
        try:
            logger.info("Relationship inference requested but not yet implemented")
            # Future: Add code to analyze column names and create foreign key relationships
            # This would require schema modification after initial table creation
        except Exception as e:
            logger.error(f"Error during relationship inference: {e}")
    
    # Return status for each table
    success_count = sum(1 for success in results.values() if success)
    logger.info(f"Completed batch load: {success_count}/{len(csv_mapping)} tables loaded successfully")
    return results

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

    # Test single file loading
    try:
        load_csv_to_sqlite(SAMPLE_CSV, DB_URI, TABLE_NAME)
        logger.info("Test single file load complete.")
    except Exception as e:
        logger.error(f"Test single file load failed: {e}")
        
    # Test multiple file loading (with the same file for simplicity)
    try:
        # In a real scenario, these would be different files
        mapping = {
            'sales1': SAMPLE_CSV,
            'sales2': SAMPLE_CSV
        }
        results = load_multiple_csvs_to_sqlite(mapping, DB_URI)
        logger.info(f"Test multiple files load results: {results}")
    except Exception as e:
        logger.error(f"Test multiple files load failed: {e}")
