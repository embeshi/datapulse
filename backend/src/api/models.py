from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

# Request Models
class AnalysisRequest(BaseModel):
    query: str = Field(..., description="User's natural language query")

class ExecuteRequest(BaseModel):
    session_id: str = Field(..., description="Session ID from the analyze endpoint")
    approved_sql: str = Field(..., description="SQL query to execute, potentially edited by the user")

# Response Models
class GeneratedSQLResponse(BaseModel):
    type: Literal["sql_generated"] = "sql_generated"
    session_id: str
    generated_sql: str
    plan: Optional[str] = None

class SuggestionResponse(BaseModel):
    type: Literal["suggestions_provided"] = "suggestions_provided"
    suggestions: str
    session_id: Optional[str] = None
    
class DataDescriptionResponse(BaseModel):
    type: Literal["data_described"] = "data_described"
    description: str
    session_id: Optional[str] = None

class ErrorResponse(BaseModel):
    error: str
    debug_suggestion: Optional[str] = None
    infeasibility_reason: Optional[str] = None
    alternative_suggestion: Optional[str] = None
    original_sql: Optional[str] = None
    session_id: Optional[str] = None

class LogEntry(BaseModel):
    step: str
    details: Optional[str] = None
    timestamp: Optional[str] = None

class AnalysisResultResponse(BaseModel):
    session_id: str
    interpretation: str
    results: List[Dict[str, Any]]
    history: Optional[List[str]] = None

class HistoryResponse(BaseModel):
    session_id: str
    log: List[Dict[str, Any]]  # Structure depends on history implementation
