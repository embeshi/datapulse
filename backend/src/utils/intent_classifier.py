import logging
import re
from typing import Tuple, Literal
from src.llm import client

logger = logging.getLogger(__name__)

def classify_user_intent(user_request: str) -> Tuple[Literal["specific", "exploratory_analytical", "exploratory_descriptive"], float]:
    """
    Classifies a user request as:
    - "specific" - A specific analysis request
    - "exploratory_analytical" - A request for analytical suggestions
    - "exploratory_descriptive" - A request for dataset description
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple containing:
        - Intent classification 
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


def _llm_classify_intent(user_request: str) -> Tuple[Literal["specific", "exploratory_analytical", "exploratory_descriptive"], float]:
    """
    Uses LLM to classify user intent with high accuracy.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple of (intent, confidence) or None if classification fails
    """
    prompt = f"""
Your task is to classify the user's data analysis request into one of three categories:
1. "specific" - The user is requesting a specific analysis that can be directly translated to SQL.
2. "exploratory_analytical" - The user is seeking analytical insights or suggestions about their data.
3. "exploratory_descriptive" - The user is asking for a description or overview of the data itself.

Examples of SPECIFIC requests:
- "How many sales did we have by region last month?"
- "What is the average order value by product category?"
- "Show me the top 10 customers by total spending."
- "Find transactions over $500 between January and March."
- "Calculate the monthly growth rate in new customer acquisitions."
- "Compare this year's sales to last year's by quarter."

Examples of EXPLORATORY_ANALYTICAL requests:
- "What insights can I get from my sales data?"
- "Suggest some interesting analyses for my customer database."
- "What are some patterns I should look for in this dataset?"
- "Suggest some analyses I can run."
- "Give me some ideas for analyzing this data."
- "What questions should I ask about this data?"

Examples of EXPLORATORY_DESCRIPTIVE requests:
- "What are these datasets about?"
- "Describe the data I have."
- "What kind of information do these tables contain?"
- "What's in this database?"
- "Show me an overview of my data."
- "What types of data do I have?"
- "Tell me about these tables."
- "What can you tell me about these datasets?"

User request: "{user_request}"

OUTPUT INSTRUCTIONS:
1. Respond with ONLY ONE OF THESE PHRASES: "specific", "exploratory_analytical", or "exploratory_descriptive"
2. Nothing else - no explanations, no json, no additional text
"""
    
    try:
        response = client.call_llm(prompt)
        # Clean and normalize the response
        response = response.strip().lower()
        
        # Ensure we got a valid classification
        if response == "exploratory_analytical":
            return "exploratory_analytical", 0.95
        elif response == "exploratory_descriptive":
            return "exploratory_descriptive", 0.95
        elif response == "specific":
            return "specific", 0.95
        else:
            # If LLM didn't follow instructions exactly, log and fall back
            logger.warning(f"LLM returned invalid classification: '{response}'")
            return None
    except Exception as e:
        logger.error(f"Error in LLM classification: {e}")
        return None


def _rule_based_classify_intent(user_request: str) -> Tuple[Literal["specific", "exploratory_analytical", "exploratory_descriptive"], float]:
    """
    Rule-based backup classification method.
    
    Args:
        user_request: The user's natural language query
        
    Returns:
        Tuple containing intent classification and confidence
    """
    # Convert to lowercase for comparison
    request_lower = user_request.lower().strip()
    
    # First check for descriptive patterns
    descriptive_patterns = [
        r"what (are|is) (these|this|the|those) (dataset|data|tables|database)s? about",
        r"(describe|tell me about|overview of|summary of) (the|these|this|my) (data|dataset|tables)",
        r"what (kind|type) of (data|information) (do |does |)(these|this|the|my) (dataset|data|tables)s? (have|contain)",
        r"what('s| is) in (these|this|the|my) (data|dataset|tables|database)",
        r"what (data|information) (do |)(i|we) have",
        r"show me (what|the) data (i|we) have"
    ]
    
    # Check for direct descriptive pattern matches
    for pattern in descriptive_patterns:
        if re.search(pattern, request_lower):
            logger.info(f"Descriptive pattern match in: '{request_lower}'")
            return "exploratory_descriptive", 0.95
    
    # Direct classification for common exploratory analytical phrases
    analytical_phrases = [
        "what are some suggested", 
        "what insights", 
        "suggest some",
        "what analysis", 
        "what can i learn from",
        "give me some insights",
        "what are the main insights",
        "show me what's interesting"
    ]
    
    # Check for direct match with common exploratory analytical phrases
    for phrase in analytical_phrases:
        if phrase in request_lower:
            logger.info(f"Direct exploratory analytical phrase match: '{phrase}' in '{request_lower}'")
            return "exploratory_analytical", 0.95
    
    # Pattern matching for exploratory analytical requests
    analytical_patterns = [
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
    
    # Check for analytical keyword matches
    analytical_keywords = [
        "suggest", "recommendation", "insights", "ideas", 
        "explore", "discover", "possibilities", "potential", 
        "interesting", "patterns", "guidance"
    ]
    
    # Count analytical pattern matches
    analytical_pattern_matches = sum(1 for pattern in analytical_patterns if re.search(pattern, request_lower))
    
    # Count analytical keyword matches
    analytical_keyword_matches = sum(1 for keyword in analytical_keywords if keyword in request_lower)
    
    # Calculate analytical confidence
    total_analytical_signals = len(analytical_patterns) + len(analytical_keywords)
    analytical_confidence = (analytical_pattern_matches + analytical_keyword_matches) / total_analytical_signals
    
    logger.debug(f"Rule-based classification for '{user_request[:30]}...': " 
                f"analytical_pattern_matches={analytical_pattern_matches}, "
                f"analytical_keyword_matches={analytical_keyword_matches}, " 
                f"analytical_confidence={analytical_confidence:.2f}")
    
    if analytical_confidence > 0.05:  # Very low threshold to capture more exploratory requests
        return "exploratory_analytical", analytical_confidence
    else:
        return "specific", 1.0 - analytical_confidence
