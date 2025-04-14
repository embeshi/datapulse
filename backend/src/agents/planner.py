# src/agents/planner.py
import logging
from src.llm import client, prompts # Use absolute imports from src

logger = logging.getLogger(__name__)

def run_planner(user_request: str, database_context: str) -> str:
    """Generates the conceptual plan using the LLM."""
    logger.info(f"Running planner for request: '{user_request[:50]}...'")
    try:
        prompt = prompts.get_planning_prompt(user_request, database_context)
        logger.info(f"Planner prompt: {prompt}\n")
        # Call the LLM with the generated prompt
        plan = client.call_llm(prompt)
        # Basic cleanup (can be expanded)
        plan = plan.strip()
        logger.info(f"Planner generated plan:\n{plan}")
        return plan
    except Exception as e:
        logger.error(f"Planner agent failed: {e}")
        raise # Re-raise for orchestration layer to handle

