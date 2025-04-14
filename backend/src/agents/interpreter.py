# src/agents/interpreter.py
import logging
from typing import List, Dict, Any
from src.llm import client, prompts

logger = logging.getLogger(__name__)

def run_interpreter(user_request: str, results: List[Dict[str, Any]]) -> str:
    """Generates the natural language interpretation using the LLM."""
    logger.info(f"Running interpreter for request: '{user_request[:50]}...' on {len(results)} results.")
    try:
        prompt = prompts.get_interpretation_prompt(user_request, results)
        interpretation = client.call_llm(prompt)
        interpretation = interpretation.strip()
        logger.info(f"Interpreter generated summary:\n{interpretation}")
        return interpretation
    except Exception as e:
        logger.error(f"Interpreter agent failed: {e}")
        raise