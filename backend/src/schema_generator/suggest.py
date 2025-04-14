import logging
from typing import List, Dict, Union, Optional
from pathlib import Path
import re
import traceback

from src.schema_generator.sampler import sample_csvs
from src.llm import client, prompts

logger = logging.getLogger(__name__)

def _validate_prisma_schema_output(llm_output: str) -> bool:
    """Performs basic checks on the LLM output for Prisma schema syntax."""
    if not llm_output or not llm_output.strip():
        logger.error("LLM returned empty schema suggestion.")
        return False
    # Check for essential blocks (can be improved with more robust parsing/regex)
    if "datasource db" not in llm_output:
        logger.error("LLM output missing 'datasource db' block.")
        return False
    if "generator client" not in llm_output:
        logger.error("LLM output missing 'generator client' block.")
        return False
    if "model " not in llm_output: # Needs at least one model
        logger.error("LLM output missing 'model' definition block.")
        return False
    # Check for common LLM explanation patterns outside comments
    lines = llm_output.strip().splitlines()
    non_comment_lines = [line for line in lines if not line.strip().startswith(("//", "#"))]
    if not non_comment_lines[0].lower().startswith(("datasource", "generator", "//", "#")):
         logger.warning("LLM output might contain leading non-schema text.")
         # Could attempt to trim here, but risky. Rely on prompt for now.
    logger.info("Basic validation of schema output passed.")
    return True

def _extract_prisma_schema_from_llm(raw_response: str) -> str:
    """Extracts schema content, attempting to remove markdown fences."""
    logger.debug(f"Raw Schema Suggestion response: {raw_response[:500]}...")
    # Regex to find ```prisma ... ``` block
    match = re.search(r"```(?:prisma)?\s*(.*?)\s*```", raw_response, re.DOTALL | re.IGNORECASE)
    if match:
        schema_content = match.group(1).strip()
        # Sometimes LLMs include the initial prompt part again, try removing known parts
        schema_content = schema_content.replace("""
// Datasource and Generator Blocks
datasource db {
  provider = "sqlite"
  url      = env("DATABASE_URL")
}

generator client {
  provider = "prisma-client-py"
  # interface = "asyncio" // Optional: uncomment if async needed
}

// Inferred Models Below
""".strip(), "").strip()
        logger.info("Extracted schema from markdown block.")
        return schema_content
    else:
        # If no markdown block, assume raw response might be schema, but apply validation
        logger.warning("No markdown block detected in schema suggestion. Using raw response.")
        return raw_response.strip()


def suggest_schema_from_csvs(csv_paths: List[Union[str, Path]]) -> Optional[str]:
    """
    Takes CSV paths, samples them, calls LLM to suggest a Prisma schema.

    Args:
        csv_paths: List of paths to input CSV files.

    Returns:
        The suggested schema content as a string, or None if generation fails.
    """
    logger.info(f"Starting schema suggestion based on CSVs: {csv_paths}")
    try:
        samples = sample_csvs(csv_paths)
        if not samples or all("Error:" in s for s in samples.values()):
            logger.error("Failed to get valid samples from CSV files.")
            return None

        prompt = prompts.get_schema_suggestion_prompt(samples)
        suggested_schema_raw = client.call_llm(prompt) # Assumes client is configured

        # Extract potentially fenced content
        suggested_schema = _extract_prisma_schema_from_llm(suggested_schema_raw)

        if not _validate_prisma_schema_output(suggested_schema):
            logger.error("LLM generated schema failed basic validation.")
            # Optionally log the invalid schema: logger.debug(f"Invalid schema attempt:\n{suggested_schema}")
            return None

        logger.info("Successfully generated and validated schema suggestion.")
        # Log first few lines for confirmation
        logger.debug(f"Suggested Schema (start):\n{suggested_schema[:500]}...")
        return suggested_schema

    except Exception as e:
        logger.error(f"Schema suggestion failed: {e}")
        logger.error(traceback.format_exc())
        return None
