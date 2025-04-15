from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, List, Optional, Union
import logging

from src.api.models import (
    AnalysisRequest, ExecuteRequest, 
    GeneratedSQLResponse, SuggestionResponse, ErrorResponse,
    AnalysisResultResponse, HistoryResponse
)
from src.orchestration.workflow import (
    initiate_analysis_async, execute_approved_analysis_async
)
from src.prisma_utils import context as prisma_context
from src.utils.intent_classifier import classify_user_intent

router = APIRouter(prefix="/api", tags=["analysis"])
logger = logging.getLogger(__name__)

# Database connection config - you might want to move this to a config file
DB_URI = "sqlite:///analysis.db"

@router.post("/analyze", 
             response_model=Union[GeneratedSQLResponse, SuggestionResponse, ErrorResponse],
             responses={
                 200: {"description": "SQL generated or insights provided"},
                 400: {"description": "Bad request"},
                 500: {"description": "Internal server error"}
             })
async def analyze(request: AnalysisRequest):
    """
    Analyze a natural language query against the database.
    Determines intent and returns either generated SQL or insight suggestions.
    """
    try:
        user_query = request.query
        logger.info(f"API: Processing analysis request: '{user_query[:50]}...'")
        
        # Analyze the request intent (exploratory vs specific)
        intent, confidence = classify_user_intent(user_query)
        logger.info(f"Query classified as {intent} (confidence: {confidence:.2f})")
        
        if intent == "exploratory":
            # For exploratory requests, generate insights
            result = await initiate_analysis_async(user_query, DB_URI)
            
            if 'error' in result:
                logger.error(f"Exploratory analysis error: {result['error']}")
                return ErrorResponse(error=result['error'])
            
            if 'insights' in result:
                logger.info(f"Returning exploratory insights for query")
                return SuggestionResponse(
                    suggestions=result['insights'],
                    session_id=result.get('session_id')
                )
        
        # For specific analysis requests, generate SQL
        result = await initiate_analysis_async(user_query, DB_URI)
        
        if 'error' in result:
            # Check if this is due to an infeasible plan
            if 'infeasibility_reason' in result:
                logger.warning(f"Infeasible analysis plan: {result.get('infeasibility_reason')}")
                return ErrorResponse(
                    error=result.get('error', "Request cannot be fulfilled with available data"),
                    infeasibility_reason=result.get('infeasibility_reason'),
                    alternative_suggestion=result.get('alternative_suggestion')
                )
            logger.error(f"Analysis error: {result['error']}")
            return ErrorResponse(error=result['error'])
        
        logger.info(f"Returning SQL for session {result['session_id']}")
        return GeneratedSQLResponse(
            session_id=result['session_id'],
            generated_sql=result['generated_sql'],
            plan=result.get('plan')  # Include plan if available
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error in /analyze endpoint")
        return ErrorResponse(error=f"Analysis failed: {str(e)}")

@router.post("/execute", 
             response_model=Union[AnalysisResultResponse, ErrorResponse],
             responses={
                 200: {"description": "SQL executed successfully"},
                 400: {"description": "Bad request"},
                 500: {"description": "Internal server error"}
             })
async def execute(request: ExecuteRequest):
    """
    Execute approved SQL query from a previous analysis session.
    Returns results and interpretation.
    """
    try:
        logger.info(f"API: Executing approved SQL for session {request.session_id}")
        
        result = await execute_approved_analysis_async(
            request.session_id, request.approved_sql
        )
        
        if 'error' in result:
            # Check if we have a debug suggestion for SQL errors
            if 'debug_suggestion' in result:
                logger.warning(f"SQL execution error with debug suggestion: {result['error']}")
                return ErrorResponse(
                    error=result['error'],
                    debug_suggestion=result.get('debug_suggestion'),
                    original_sql=result.get('original_sql'),
                    session_id=result.get('session_id')
                )
            logger.error(f"SQL execution error: {result['error']}")
            return ErrorResponse(error=result['error'])
        
        logger.info(f"Returning execution results for session {request.session_id}")
        return AnalysisResultResponse(
            session_id=request.session_id,
            interpretation=result['interpretation'],
            results=result['results'],
            history=result.get('history')
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error in /execute endpoint")
        return ErrorResponse(error=f"Execution failed: {str(e)}")

@router.get("/history/{session_id}", 
            response_model=HistoryResponse,
            responses={
                200: {"description": "History retrieved successfully"},
                404: {"description": "Session not found"},
                500: {"description": "Internal server error"}
            })
async def get_history(session_id: str):
    """
    Retrieve the history of steps and artifacts for an analysis session.
    """
    try:
        logger.info(f"API: Retrieving history for session {session_id}")
        
        # This would call your history manager once implemented in Phase 5
        # For now, use workflow state store as a simple implementation
        from src.orchestration.workflow import WORKFLOW_STATE_STORE
        
        if session_id not in WORKFLOW_STATE_STORE:
            logger.warning(f"History not found for session {session_id}")
            raise HTTPException(
                status_code=404, 
                detail=f"History not found for session ID: {session_id}"
            )
        
        # Very basic implementation - in reality you'd use a proper history manager
        session_state = WORKFLOW_STATE_STORE.get(session_id, {})
        
        # Create a simple log from the available state
        log = []
        for key, value in session_state.items():
            # Skip complex objects for simplicity
            if isinstance(value, (str, int, float, bool)) or value is None:
                log.append({"step": key, "details": str(value)[:100] if value else None})
        
        logger.info(f"Returning history log with {len(log)} entries")
        return HistoryResponse(
            session_id=session_id,
            log=log
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in /history endpoint")
        return ErrorResponse(error=f"Failed to retrieve history: {str(e)}")
