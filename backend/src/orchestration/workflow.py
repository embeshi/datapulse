# src/orchestration/workflow.py
import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple
import traceback

# Import necessary functions from other modules (use absolute paths from src)
from src.data_handling import db_utils
from src.agents import planner, sql_generator, interpreter
# Assuming history manager will be implemented later
# from src.history import manager as history_manager

logger = logging.getLogger(__name__)

# --- Basic In-Memory State Store (Replace with Persistent Store Later - Phase 5) ---
# WARNING: Not suitable for production! Resets on app restart, not scalable.
WORKFLOW_STATE_STORE: Dict[str, Dict[str, Any]] = {}
logger.warning("Using basic in-memory WORKFLOW_STATE_STORE. State will be lost on restart.")
# -----------------------------------------------------------------------------------

def initiate_analysis(user_request: str, db_uri: str) -> Dict[str, str]:
    """
    Starts the analysis workflow: gets context, plans, generates SQL.
    Stores intermediate state associated with a new session ID.

    Args:
        user_request: The user's natural language query.
        db_uri: The database URI string.

    Returns:
        Dictionary {'session_id': str, 'generated_sql': str} on success.
        Dictionary {'error': str} on failure.
    """
    session_id = uuid.uuid4().hex
    logger.info(f"Initiating analysis for request: '{user_request[:50]}...'. Session ID: {session_id}")

    try:
        engine = db_utils.get_sqlalchemy_engine(db_uri)
        db_context = db_utils.get_database_context_string(engine)
        if db_context.startswith("Error:") : # Check if context generation failed
             raise ValueError(f"Failed to get database context: {db_context}")

        # Log initial step (using simple print for now, replace with history manager later)
        print(f"[History Stub - {session_id}] Step: Request Received - Input: {user_request}")

        plan = planner.run_planner(user_request, db_context)
        print(f"[History Stub - {session_id}] Step: Plan Generated - Output:\n{plan}")

        generated_sql = sql_generator.run_sql_generator(plan, db_context)
        print(f"[History Stub - {session_id}] Step: SQL Generated - Output:\n{generated_sql}")

        # Store state needed for the execution step
        WORKFLOW_STATE_STORE[session_id] = {
            'user_request': user_request,
            'db_context': db_context, # Storing context might be large, consider alternatives
            'plan': plan,
            'generated_sql': generated_sql,
        }
        logger.info(f"Stored initial state for session_id: {session_id}")

        return {'session_id': session_id, 'generated_sql': generated_sql}

    except Exception as e:
        logger.error(f"Error during analysis initiation (Session: {session_id}): {e}")
        logger.error(traceback.format_exc())
        # Clean up potentially partially stored state?
        if session_id in WORKFLOW_STATE_STORE:
            del WORKFLOW_STATE_STORE[session_id]
        return {'error': f"Analysis initiation failed: {e}"}


def execute_approved_analysis(session_id: str, approved_sql: str, db_uri: str) -> Dict[str, Any]:
    """
    Executes the approved SQL, interprets results, and returns the final output.
    Retrieves necessary context using the session_id.

    Args:
        session_id: The unique identifier for the analysis workflow.
        approved_sql: The SQL string approved (potentially edited) by the user.
        db_uri: The database URI string.

    Returns:
        Dictionary containing {'interpretation': str, 'results': List[Dict], 'history': List} on success.
        Dictionary {'error': str} on failure.
    """
    logger.info(f"Executing approved analysis for session_id: {session_id}")

    # Retrieve state
    session_state = WORKFLOW_STATE_STORE.get(session_id)
    if not session_state:
        logger.error(f"Session ID not found in state store: {session_id}")
        return {'error': f"Invalid or expired session ID: {session_id}"}

    original_request = session_state.get('user_request', 'Unknown Request') # Retrieve original request
    # Optionally retrieve plan/context if needed by interpreter, though current prompt doesn't use them

    try:
        # Log approval (stub)
        print(f"[History Stub - {session_id}] Step: SQL Approved - Input:\n{approved_sql}")

        engine = db_utils.get_sqlalchemy_engine(db_uri)
        results, error = db_utils.execute_sql(engine, approved_sql)

        # Log execution (stub)
        if error:
            print(f"[History Stub - {session_id}] Step: SQL Execution Failed - Output: {error}")
            raise ValueError(f"SQL Execution failed: {error}")
        else:
             print(f"[History Stub - {session_id}] Step: SQL Execution Succeeded - Output: {len(results)} rows")


        interpretation = interpreter.run_interpreter(original_request, results)
        print(f"[History Stub - {session_id}] Step: Interpretation Generated - Output:\n{interpretation}")

        # Clean up state store for this session
        del WORKFLOW_STATE_STORE[session_id]
        logger.info(f"Cleaned up state for session_id: {session_id}")

        # Retrieve actual history later in Phase 5
        history_stub = [
            f"Request: {original_request}",
            f"Plan: {session_state.get('plan', 'N/A')}",
            f"Generated SQL: {session_state.get('generated_sql', 'N/A')}",
            f"Approved SQL: {approved_sql}",
            f"Execution: {len(results)} rows",
            f"Interpretation: {interpretation}"
        ]

        return {'interpretation': interpretation, 'results': results, 'history': history_stub} # Return stub history

    except Exception as e:
        logger.error(f"Error during analysis execution (Session: {session_id}): {e}")
        logger.error(traceback.format_exc())
        # Clean up state store even on failure
        if session_id in WORKFLOW_STATE_STORE:
            del WORKFLOW_STATE_STORE[session_id]
        return {'error': f"Analysis execution failed: {e}"}

# Example Usage (can be called from main_cli.py or app.py)
if __name__ == "__main__":
     # --- This block demonstrates the TWO-STEP flow ---
     logger.info("\n--- Testing Orchestration Workflow ---")
     TEST_DB_URI = 'sqlite:///analysis.db' # Make sure DB exists and has data

     # Step 1: Initiate analysis
     user_query = "What are the different product categories and how many products in each?"
     logger.info(f"\n[Test Flow Step 1: Initiate Analysis for '{user_query}']")
     initiation_result = initiate_analysis(user_query, TEST_DB_URI)

     if 'error' in initiation_result:
         logger.error(f"Initiation failed: {initiation_result['error']}")
     else:
         test_session_id = initiation_result['session_id']
         generated_sql_result = initiation_result['generated_sql']
         logger.info(f"Initiation successful. Session ID: {test_session_id}")
         print(f"Generated SQL:\n{generated_sql_result}")

         # Step 2: Simulate User Approval (using generated SQL directly here)
         # In a real app, there would be a UI step here.
         approved_sql_for_test = generated_sql_result
         logger.info(f"\n[Test Flow Step 2: Execute Approved Analysis (Session: {test_session_id})]")
         final_result = execute_approved_analysis(test_session_id, approved_sql_for_test, TEST_DB_URI)

         if 'error' in final_result:
             logger.error(f"Execution failed: {final_result['error']}")
         else:
             logger.info("Execution successful.")
             print("\n--- Final Interpretation ---")
             print(final_result['interpretation'])
             print("\n--- Raw Results (Sample) ---")
             print(final_result['results'][:3]) # Print first 3 rows
             # print("\n--- History (Stub) ---")
             # print("\n".join(final_result['history']))

     logger.info("\n--- Orchestration Workflow Test Complete ---")