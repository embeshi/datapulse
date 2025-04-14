#!/usr/bin/env python
# scripts/generate_schema.py

import sys
import os
import logging
from pathlib import Path
import subprocess
import argparse

# Add the parent directory to the Python path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.schema_generator.suggest import suggest_schema_from_csvs

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
PRISMA_SCHEMA_PATH = Path("prisma") / "schema.prisma"
PRISMA_ENV_PATH = Path(".env.local")  # Path to .env.local file for DATABASE_URL
DEFAULT_DB_PATH = Path("analysis.db")

def setup_env_file(db_path: Path):
    """Create .env.local file with DATABASE_URL for Prisma"""
    abs_db_path = db_path.resolve()
    env_content = f'DATABASE_URL="file:{abs_db_path}"\n'
    
    PRISMA_ENV_PATH.write_text(env_content)
    logger.info(f"Created {PRISMA_ENV_PATH} with DATABASE_URL={abs_db_path}")

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
    
    # Write schema to file
    output_path.write_text(schema)
    logger.info(f"Schema written to {output_path}")
    
    # Print schema for user review
    print("\n--- Suggested Schema ---\n")
    print(schema)
    print("\n--- End Schema ---\n")
    
    if not args.apply:
        logger.info("Schema generated but not applied. Run with --apply to apply to database.")
        return True
    
    # User confirmation to proceed
    confirmation = input("Apply this schema to the database? (y/N): ").strip().lower()
    if confirmation != 'y':
        logger.info("Schema application cancelled by user")
        return False
    
    # Setup environment file
    setup_env_file(db_path)
    
    # Run prisma generate
    success, output = run_prisma_command(["generate"])
    if not success:
        return False
    
    # Run prisma db push
    success, output = run_prisma_command(["db", "push", "--accept-data-loss"])
    if not success:
        return False
    
    logger.info(f"Schema successfully applied to database: {db_path}")
    return True

if __name__ == "__main__":
    if setup_prisma_schema():
        logger.info("Schema generation process completed successfully")
        sys.exit(0)
    else:
        logger.error("Schema generation process failed")
        sys.exit(1)
