import logging
import re
from typing import Tuple, Literal

logger = logging.getLogger(__name__)

def classify_user_intent(user_request: str) -> Tuple[Literal["specific", "exploratory"], float]:
    """
    Classifies a user request as either a specific analysis request
    or an exploratory/insight-seeking request.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple containing:
        - Intent classification ("specific" or "exploratory")
        - Confidence score (0.0-1.0)
    """
    # Convert to lowercase for comparison
    request_lower = user_request.lower().strip()
    
    # Direct classification for common exploratory phrases
    direct_exploratory_phrases = [
        "what are some suggested", 
        "what insights", 
        "suggest some",
        "what analysis", 
        "what can you tell me about",
        "what can i learn from",
        "give me some insights",
        "what are the main insights",
        "show me what's interesting"
    ]
    
    # Check for direct match with common exploratory phrases first
    for phrase in direct_exploratory_phrases:
        if phrase in request_lower:
            logger.info(f"Direct exploratory phrase match: '{phrase}' in '{request_lower}'")
            return "exploratory", 0.95
    
    # Pattern matching for exploratory requests
    exploratory_patterns = [
        r"what (insight|analysis|information) can (i|we|you) (get|derive|extract)",
        r"suggest (some|potential|possible) (analysis|insights|questions)",
        r"(what|which) (questions|analyses) (should|could|can) (i|we) (ask|explore)",
        r"help me (understand|explore|analyze) (this|the|these) data",
        r"what (can|could) (i|we) learn from (this|these) data",
        r"what's interesting (about|in) (this|the|these) data",
        r"(show|tell) me (what|some) insights",
        r"(identify|find) (patterns|trends|anomalies|outliers)",
        r"give me (ideas|suggestions) for analysis",
        r"(how|what's the best way to) (analyze|understand) (this|these|the) data"
    ]
    
    # Check for direct exploratory keywords
    exploratory_keywords = [
        "suggest", "recommendation", "insights", "ideas", 
        "explore", "discover", "possibilities", "potential", 
        "interesting", "patterns", "overview", "guidance"
    ]
    
    # Count pattern matches
    pattern_matches = sum(1 for pattern in exploratory_patterns if re.search(pattern, request_lower))
    
    # Count keyword matches
    keyword_matches = sum(1 for keyword in exploratory_keywords if keyword in request_lower)
    
    # Calculate confidence based on matches
    total_signals = len(exploratory_patterns) + len(exploratory_keywords)
    confidence = (pattern_matches + keyword_matches) / total_signals
    
    # Apply threshold - lowered threshold to make it more sensitive to exploratory queries
    logger.debug(f"Intent classification for '{user_request[:30]}...': " 
                f"pattern_matches={pattern_matches}, keyword_matches={keyword_matches}, " 
                f"confidence={confidence:.2f}")
    
    if confidence > 0.05:  # Very low threshold to capture more exploratory requests
        return "exploratory", confidence
    else:
        return "specific", 1.0 - confidence
