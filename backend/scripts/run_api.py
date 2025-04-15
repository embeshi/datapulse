#!/usr/bin/env python
# scripts/run_api.py

import sys
import os
import logging
from pathlib import Path
import uvicorn

# Add the parent directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Run the FastAPI server"""
    logger.info("Starting DataWeave AI API server")
    
    # Check for database file
    db_path = Path("analysis.db")
    if not db_path.exists():
        logger.warning("Database file not found: analysis.db")
        logger.warning("Please run data loading scripts before making API calls")
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the FastAPI app with uvicorn
    uvicorn.run(
        "src.api.main:app", 
        host="0.0.0.0", 
        port=port, 
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
