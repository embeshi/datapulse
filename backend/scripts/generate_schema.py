#!/usr/bin/env python
# scripts/generate_schema.py

import sys
import os
import logging
import re
import traceback
from pathlib import Path
import subprocess
import argparse
from src.data_handling.dataset_analysis import prompt_and_analyze_datasets

# Add the parent directory to the Python path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schema_generator.suggest import suggest_schema_from_csvs

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
PRISMA_SCHEMA_PATH = Path("prisma") / "schema.prisma"
DEFAULT_DB_PATH = Path("analysis.db")

def modify_schema_for_direct_db_url(schema_content: str, db_path: Path) -> str:
    """Modify the schema to use a direct file URL instead of env variable"""
    abs_db_path = db_path.resolve()
    # Replace env("DATABASE_URL") with direct file path
    modified_schema = re.sub(
        r'url\s*=\s*env\(\s*"DATABASE_URL"\s*\)',
        f'url = "file:{abs_db_path}"',
        schema_content
    )
    logger.info(f"Modified schema to use direct DB path: file:{abs_db_path}")
    return modified_schema

def run_prisma_command(command: list):
    """Run a Prisma CLI command and return the result"""
    try:
        logger.info(f"Running: prisma {' '.join(command)}")
        result = subprocess.run(["prisma"] + command, 
                               capture_output=True, 
                               text=True, 
                               check=False)
        
        if result.returncode != 0:
            logger.error(f"Prisma command failed with exit code {result.returncode}")
            logger.error(f"Error output: {result.stderr}")
            return False, result.stderr
        
        logger.info(f"Prisma command successful")
        return True, result.stdout
    except Exception as e:
        logger.error(f"Failed to run Prisma command: {e}")
        return False, str(e)

def setup_prisma_schema():
    """Generate and validate a Prisma schema from CSV files"""
    parser = argparse.ArgumentParser(description="Generate a Prisma schema from CSV files")
    parser.add_argument("csv_files", nargs="+", help="CSV files to analyze")
    parser.add_argument("--output", "-o", default=str(PRISMA_SCHEMA_PATH), 
                      help=f"Output path for schema.prisma (default: {PRISMA_SCHEMA_PATH})")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH),
                      help=f"Path for the SQLite database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--apply", action="store_true", 
                      help="Apply the schema to the database")
    
    args = parser.parse_args()
    
    csv_paths = [Path(p) for p in args.csv_files]
    output_path = Path(args.output)
    db_path = Path(args.db)
    
    # Make sure all CSV files exist
    missing_files = [p for p in csv_paths if not p.exists()]
    if missing_files:
        logger.error(f"CSV files not found: {', '.join(str(p) for p in missing_files)}")
        return False
    
    # Create the output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get schema suggestion
    logger.info(f"Generating schema suggestion from {len(csv_paths)} CSV files...")
    schema = suggest_schema_from_csvs(csv_paths)
    
    if not schema:
        logger.error("Failed to generate schema suggestion")
        return False
    
    # Modify schema to use direct DB path instead of env variable
    modified_schema = modify_schema_for_direct_db_url(schema, db_path)
    
    # Write modified schema to file
    output_path.write_text(modified_schema)
    logger.info(f"Schema written to {output_path}")
    
    # Print schema for user review
    print("\n--- Suggested Schema ---\n")
    print(modified_schema)
    print("\n--- End Schema ---\n")
    
    if not args.apply:
        logger.info("Schema generated but not applied. Run with --apply to apply to database.")
        return True
    
    # User confirmation to proceed
    confirmation = input("Apply this schema to the database? (y/N): ").strip().lower()
    if confirmation != 'y':
        logger.info("Schema application cancelled by user")
        return False
    
    # Run prisma generate
    success, output = run_prisma_command(["generate"])
    if not success:
        return False
    
    # Run prisma db push
    success, output = run_prisma_command(["db", "push", "--accept-data-loss"])
    if not success:
        return False
    
    logger.info(f"Schema successfully applied to database: {db_path}")
    
    # Now let's load the data from CSV files into the tables
    try:
        # Import the loader here to avoid circular imports
        from src.data_handling.loader import load_multiple_csvs_to_sqlite
        
        # Create a mapping from CSV files to table names using proper casing from Prisma schema
        # Extract table mapping info from generated schema
        table_mappings = {}
        schema_text = output_path.read_text()
        
        # Look for both model blocks and their @@map directives to get correct table names
        model_matches = re.finditer(r'model\s+(\w+)\s*{([^}]*)}', schema_text, re.DOTALL)
        for model_match in model_matches:
            model_name = model_match.group(1)  # PascalCase model name
            model_body = model_match.group(2)
            
            # Check if there's a @@map directive
            map_match = re.search(r'@@map\("([^"]+)"\)', model_body)
            if map_match:
                actual_table_name = map_match.group(1)
            else:
                # If no @@map, the actual table name is the model name (Prisma default)
                actual_table_name = model_name
            
            # Store both versions for flexible matching
            table_mappings[model_name.lower()] = actual_table_name
            table_mappings[actual_table_name.lower()] = actual_table_name
        
        logger.info(f"Extracted table mappings from schema: {table_mappings}")
        
        # Create a mapping from CSV files to correct table names
        csv_mapping = {}
        for csv_path in csv_paths:
            # Extract the base name without extension as potential table name
            base_name = Path(csv_path).stem.lower()
            
            # Use the correct table name from mappings if available, otherwise use base name
            if base_name in table_mappings:
                table_name = table_mappings[base_name]
                logger.info(f"Mapping CSV {csv_path} to table '{table_name}' based on schema")
            else:
                # If we can't find a mapping, use the original name but log a warning
                table_name = base_name
                logger.warning(f"Could not find table mapping for {base_name}, using as-is")
            
            csv_mapping[table_name] = str(csv_path)
        
        # Create a database URI for SQLAlchemy
        db_uri = f"sqlite:///{db_path.resolve()}"
        
        logger.info(f"Loading data from CSV files into database: {csv_mapping}")
        results = load_multiple_csvs_to_sqlite(csv_mapping, db_uri)
        
        # Check if all files were loaded successfully
        if all(results.values()):
            logger.info("All data loaded successfully into the database.")
        else:
            # Log which files failed to load
            failed_tables = [table for table, success in results.items() if not success]
            logger.warning(f"Some tables failed to load: {failed_tables}")
            print(f"\nWARNING: Some tables failed to load: {failed_tables}")
        
        # After loading data, prompt for dataset analysis
        if any(results.values()):  # Only if some tables were loaded successfully
            try:
                prompt_and_analyze_datasets(csv_mapping)
            except Exception as e:
                logger.error(f"Error during dataset analysis: {e}")
                logger.error(traceback.format_exc())
    
    except Exception as e:
        logger.error(f"Error loading data into the database: {e}")
        logger.error(traceback.format_exc())
        print(f"\nERROR: Failed to load data: {e}")
        # We don't return False here because the schema was applied successfully
        # We just couldn't load the data
    
    return True

if __name__ == "__main__":
    if setup_prisma_schema():
        logger.info("Schema generation process completed successfully")
        sys.exit(0)
    else:
        logger.error("Schema generation process failed")
        sys.exit(1)
