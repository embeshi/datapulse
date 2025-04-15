# src/agents/planner.py
import logging
from typing import Literal
from src.llm import client, prompts # Use absolute imports from src

logger = logging.getLogger(__name__)

def run_planner(user_request: str, database_context: str, 
               mode: Literal["plan", "insights"] = "plan") -> str:
    """
    Generates either a conceptual plan for SQL generation or
    suggested insights/analyses based on the database context.

    Args:
        user_request: The user's natural language query.
        database_context: String containing schema and data summaries.
        mode: "plan" for SQL execution planning, "insights" for suggesting analyses.

    Returns:
        The generated plan or insights as a string.
    """
    if mode == "insights":
        logger.info(f"Running planner in insights mode for exploratory request")
        try:
            prompt = prompts.get_insight_suggestion_prompt(database_context)
            suggestions = client.call_llm(prompt)
            suggestions = suggestions.strip()
            logger.info(f"Planner generated insight suggestions:\n{suggestions[:200]}...")
            return suggestions
        except Exception as e:
            logger.error(f"Planner insights generation failed: {e}")
            raise  # Re-raise for orchestration layer to handle
    else:
        # Regular planning mode
        logger.info(f"Running planner in standard mode for request: '{user_request[:50]}...'")
        try:
            prompt = prompts.get_planning_prompt(user_request, database_context)
            plan = client.call_llm(prompt)
            plan = plan.strip()
            logger.info(f"Planner generated plan:\n{plan}")
            return plan
        except Exception as e:
            logger.error(f"Planner agent failed: {e}")
            raise  # Re-raise for orchestration layer to handle

