#!/usr/bin/env python
# scripts/test_workflow.py

import sys
import os
import logging
from pathlib import Path
import argparse
import traceback
import asyncio

# Add the parent directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import our modules
from src.orchestration.workflow import (
    initiate_analysis, execute_approved_analysis,
    initiate_analysis_async, execute_approved_analysis_async
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Main function
async def main():
    parser = argparse.ArgumentParser(description="Test the DataWeave AI workflow")
    parser.add_argument("--query", "-q", default="What are the most expensive products in each category?",
                      help="Natural language query to analyze")
    parser.add_argument("--db", default="analysis.db",
                      help="Path to SQLite database file (default: analysis.db)")
    parser.add_argument("--async", action="store_true", dest="use_async",
                      help="Use async workflow implementation")
    
    args = parser.parse_args()
    
    # Create DB URI
    db_uri = f"sqlite:///{args.db}"
    
    # Check if DB exists
    if not Path(args.db).exists():
        logger.error(f"Database file {args.db} not found")
        sys.exit(1)
    
    logger.info(f"Testing {'async' if args.use_async else 'sync'} workflow")
    logger.info(f"Query: {args.query}")
    logger.info(f"Database: {args.db}")
    
    try:
        # Step 1: Initiate analysis
        logger.info("\n--- STEP 1: Initiate Analysis ---")
        if args.use_async:
            initiation_result = await initiate_analysis_async(args.query, db_uri)
        else:
            initiation_result = initiate_analysis(args.query, db_uri)
        
        if 'error' in initiation_result:
            logger.error(f"Analysis initiation failed: {initiation_result['error']}")
            sys.exit(1)
        
        session_id = initiation_result['session_id']
        generated_sql = initiation_result['generated_sql']
        
        logger.info(f"Session ID: {session_id}")
        
        # Check if there was plan refinement
        if 'initial_plan' in initiation_result and 'final_plan' in initiation_result:
            initial_plan = initiation_result.get('initial_plan', '')
            final_plan = initiation_result.get('final_plan', '')
            
            if initial_plan != final_plan:
                print("\nInitial Plan (before validation):")
                print("-" * 40)
                print(initial_plan)
                print("-" * 40)
                
                print("\nRefined Plan (after validation):")
                print("-" * 40)
                print(final_plan)
                print("-" * 40)
        
        print("\nGenerated SQL:")
        print("-" * 40)
        print(generated_sql)
        print("-" * 40)
        
        # Ask for user approval
        print("\nDo you want to:")
        print("1. Execute the SQL as is")
        print("2. Edit the SQL before execution")
        print("3. Cancel and exit")
        
        choice = input("\nEnter your choice (1/2/3): ").strip()
        
        if choice == '3':
            logger.info("Execution cancelled by user")
            sys.exit(0)
        
        approved_sql = generated_sql
        
        if choice == '2':
            print("\nEdit the SQL below:")
            print("-" * 40)
            
            # Support multi-line editing
            print("Enter your SQL (press Ctrl+D or Ctrl+Z+Enter when done):")
            lines = []
            try:
                while True:
                    lines.append(input())
            except EOFError:
                pass
            
            if lines:
                approved_sql = "\n".join(lines)
        
        # Step 2: Execute approved analysis
        logger.info("\n--- STEP 2: Execute Approved Analysis ---")
        if args.use_async:
            final_result = await execute_approved_analysis_async(session_id, approved_sql)
        else:
            final_result = execute_approved_analysis(session_id, approved_sql)
        
        if 'error' in final_result:
            logger.error(f"Analysis execution failed: {final_result['error']}")
            
            # Check if we have a debug suggestion
            if 'debug_suggestion' in final_result:
                print("\nSQL Execution Error:", final_result['error'])
                print("\nDebug Suggestion SQL:")
                print("-" * 60)
                print(final_result['debug_suggestion'])
                print("-" * 60)
                
                # Ask if user wants to try the suggested fix
                print("\nDo you want to:")
                print("1. Try the suggested SQL fix")
                print("2. Skip and exit")
                
                choice = input("\nEnter your choice (1/2): ").strip()
                
                if choice == '1':
                    # Execute with the suggested fix
                    logger.info("\n--- STEP 3: Execute Debug Suggestion ---")
                    debug_sql = final_result['debug_suggestion']
                    session_id = final_result['session_id']
                    
                    if args.use_async:
                        retry_result = await execute_approved_analysis_async(session_id, debug_sql)
                    else:
                        retry_result = execute_approved_analysis(session_id, debug_sql)
                    
                    if 'error' in retry_result:
                        logger.error(f"Debug suggestion execution also failed: {retry_result['error']}")
                        sys.exit(1)
                    else:
                        # Update final_result with successful retry
                        final_result = retry_result
                else:
                    sys.exit(1)
            else:
                sys.exit(1)
        
        # Display results
        print("\nInterpreted Results:")
        print("=" * 60)
        print(final_result['interpretation'])
        print("=" * 60)
        
        print("\nRaw Results (first 5 rows):")
        print("-" * 60)
        for row in final_result['results'][:5]:
            print(row)
        
        if len(final_result['results']) > 5:
            print(f"... {len(final_result['results']) - 5} more rows ...")
        
        logger.info("Workflow test completed successfully")
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
