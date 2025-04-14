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
    
    # Case 1: Look for ```prisma ... ``` block first
    match = re.search(r"```(?:prisma)?\s*(.*?)\s*```", raw_response, re.DOTALL | re.IGNORECASE)
    if match:
        schema_content = match.group(1).strip()
        logger.info("Extracted schema from markdown block.")
        return schema_content
    
    # Case 2: Look for datasource db {...} pattern directly in the response
    datasource_match = re.search(r"(datasource\s+db\s*{.*?})", raw_response, re.DOTALL)
    if datasource_match:
        # If we found a datasource block, assume the rest of the response is also part of the schema
        logger.info("Detected datasource block directly in response.")
        return raw_response.strip()
    
    # Case 3: If the response starts with comments (`//`), it might be a schema without markdown
    if raw_response.strip().startswith("//"):
        logger.info("Response starts with comments, assuming it's a schema.")
        return raw_response.strip()
    
    # Case 4: Last resort - clean the response and check if it has schema structure
    cleaned_response = raw_response.strip()
    
    # Remove any preamble text before what looks like a schema section
    schema_start_indicators = ["datasource", "generator", "model"]
    for indicator in schema_start_indicators:
        pattern = re.compile(f".*?({indicator}\\s+\\w+\\s*{{)", re.DOTALL)
        match = pattern.match(cleaned_response)
        if match:
            start_index = match.start(1)
            cleaned_response = cleaned_response[start_index:]
            logger.info(f"Trimmed response to start at '{indicator}' block.")
            break
    
    logger.warning("No markdown block detected in schema suggestion. Using cleaned response.")
    return cleaned_response


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

        # Log sample data to help debug
        logger.debug(f"Generated CSV samples: {list(samples.keys())}")
        
        prompt = prompts.get_schema_suggestion_prompt(samples)
        logger.debug(f"LLM prompt (first 500 chars): {prompt[:500]}...")
        
        # Add a fallback template in case the LLM fails to generate a proper schema
        default_schema = """// Default schema template used as fallback
datasource db {
  provider = "sqlite"
  url      = env("DATABASE_URL")
}

generator client {
  provider = "prisma-client-py"
}

// Sample model stub - replace with proper models after review
model DefaultTable {
  id Int @id @default(autoincrement())
  // Add fields based on your CSV data
}
"""
        
        try:
            suggested_schema_raw = client.call_llm(prompt)
            logger.debug(f"Raw LLM response (first 500 chars): {suggested_schema_raw[:500]}...")
        except Exception as llm_err:
            logger.error(f"LLM call failed: {llm_err}")
            logger.warning("Using default schema template as fallback")
            return default_schema

        # Extract potentially fenced content
        suggested_schema = _extract_prisma_schema_from_llm(suggested_schema_raw)
        
        # Log the extracted schema for debugging
        logger.debug(f"Extracted schema (first 500 chars): {suggested_schema[:500]}...")

        if not _validate_prisma_schema_output(suggested_schema):
            logger.error("LLM generated schema failed basic validation.")
            logger.debug(f"Invalid schema attempt:\n{suggested_schema}")
            # Return default schema as fallback
            logger.warning("Using default schema template as fallback")
            return default_schema

        logger.info("Successfully generated and validated schema suggestion.")
        return suggested_schema

    except Exception as e:
        logger.error(f"Schema suggestion failed: {e}")
        logger.error(traceback.format_exc())
        # Return default schema template as fallback
        return """// Fallback schema template due to error
datasource db {
  provider = "sqlite"
  url      = env("DATABASE_URL")
}

generator client {
  provider = "prisma-client-py"
}

// THIS IS A FALLBACK SCHEMA - ERROR OCCURRED DURING GENERATION
// Review this schema and adjust based on your CSV files
model DefaultTable {
  id Int @id @default(autoincrement())
  // Add fields based on your CSV data
}
"""
