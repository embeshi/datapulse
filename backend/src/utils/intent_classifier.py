import logging
import re
from typing import Tuple, Literal
from src.llm import client

logger = logging.getLogger(__name__)

def classify_user_intent(user_request: str) -> Tuple[Literal["specific", "exploratory"], float]:
    """
    Classifies a user request as either a specific analysis request
    or an exploratory/insight-seeking request using both LLM and rules-based approaches.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple containing:
        - Intent classification ("specific" or "exploratory")
        - Confidence score (0.0-1.0)
    """
    # First, try LLM-based classification for highest accuracy
    try:
        llm_classification = _llm_classify_intent(user_request)
        if llm_classification:
            intent, confidence = llm_classification
            logger.info(f"LLM classified request as '{intent}' with confidence {confidence}")
            return intent, confidence
    except Exception as e:
        logger.warning(f"LLM classification failed, falling back to rule-based: {e}")
    
    # Fall back to rule-based classification if LLM fails
    return _rule_based_classify_intent(user_request)


def _llm_classify_intent(user_request: str) -> Tuple[Literal["specific", "exploratory"], float]:
    """
    Uses LLM to classify user intent with high accuracy.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple of (intent, confidence) or None if classification fails
    """
    prompt = f"""
Your task is to classify the user's data analysis request as either:
1. "exploratory" - The user is seeking general insights, suggestions, or guidance about their data.
2. "specific" - The user is requesting a specific analysis that can be directly translated to SQL.

Examples of EXPLORATORY requests:
- "What insights can I get from my sales data?"
- "Suggest some interesting analyses for my customer database."
- "What are some patterns I should look for in this dataset?"
- "What are some suggested analysis or insights we could get from these datasets?"
- "What can you tell me about these tables?"
- "Give me some ideas for analyzing this data."

Examples of SPECIFIC requests:
- "How many sales did we have by region last month?"
- "What is the average order value by product category?"
- "Show me the top 10 customers by total spending."
- "Find transactions over $500 between January and March."
- "Calculate the monthly growth rate in new customer acquisitions."
- "Compare this year's sales to last year's by quarter."

User request: "{user_request}"

OUTPUT INSTRUCTIONS:
1. Respond with ONLY ONE WORD - either "exploratory" or "specific"
2. Nothing else - no explanations, no json, no additional text
"""
    
    try:
        response = client.call_llm(prompt)
        # Clean and normalize the response
        response = response.strip().lower()
        
        # Ensure we got a valid classification
        if response == "exploratory":
            return "exploratory", 0.95
        elif response == "specific":
            return "specific", 0.95
        else:
            # If LLM didn't follow instructions exactly, log and fall back
            logger.warning(f"LLM returned invalid classification: '{response}'")
            return None
    except Exception as e:
        logger.error(f"Error in LLM classification: {e}")
        return None


def _rule_based_classify_intent(user_request: str) -> Tuple[Literal["specific", "exploratory"], float]:
    """
    Rule-based backup classification method.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple containing intent classification and confidence
    """
    # Convert to lowercase for comparison
    request_lower = user_request.lower().strip()
    
    # Direct classification for common exploratory phrases (high confidence matches)
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
    
    # Apply threshold - very low threshold to ensure we catch exploratory requests
    logger.debug(f"Rule-based classification for '{user_request[:30]}...': " 
                f"pattern_matches={pattern_matches}, keyword_matches={keyword_matches}, " 
                f"confidence={confidence:.2f}")
    
    if confidence > 0.05:  # Very low threshold to capture more exploratory requests
        return "exploratory", confidence
    else:
        return "specific", 1.0 - confidence
