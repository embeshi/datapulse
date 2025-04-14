import logging
from typing import List, Dict, Union, Optional, Tuple
from pathlib import Path
import re
import traceback

from src.schema_generator.sampler import sample_csvs
from src.llm import client, prompts

logger = logging.getLogger(__name__)

def _validate_prisma_schema_output(llm_output: str) -> Tuple[bool, Optional[str]]:
    """
    Performs basic checks on the LLM output for Prisma schema syntax.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not llm_output or not llm_output.strip():
        logger.error("LLM returned empty schema suggestion.")
        return False, "Empty schema suggestion"
    
    # Check for essential blocks (can be improved with more robust parsing/regex)
    if "datasource db" not in llm_output:
        logger.error("LLM output missing 'datasource db' block.")
        return False, "Missing 'datasource db' block"
        
    if "generator client" not in llm_output:
        logger.error("LLM output missing 'generator client' block.")
        return False, "Missing 'generator client' block"
        
    if "model " not in llm_output: # Needs at least one model
        logger.error("LLM output missing 'model' definition block.")
        return False, "Missing model definition block"
    
    # Check for common LLM explanation patterns outside comments
    lines = llm_output.strip().splitlines()
    non_comment_lines = [line for line in lines if not line.strip().startswith(("//", "#"))]
    
    if not non_comment_lines[0].lower().startswith(("datasource", "generator", "//", "#")):
         logger.warning("LLM output might contain leading non-schema text.")
         # Could attempt to trim here, but risky. Rely on prompt for now.
    
    # Check for potentially dangerous types where nullable might be required
    # This is a heuristic to warn about possible data type issues
    models = re.finditer(r'model\s+(\w+)\s*{([^}]*)}', llm_output, re.DOTALL)
    
    # Collect models and their relations for validation
    model_relations = {}
    
    for model_match in models:
        model_name = model_match.group(1)
        model_body = model_match.group(2)
        
        # Look for non-nullable fields (no question mark) of types that might cause loading issues
        risky_fields = re.finditer(r'\s*(\w+)\s+(Int|Float|DateTime)\s+(?!\?)', model_body)
        for field_match in risky_fields:
            field_name = field_match.group(1)
            field_type = field_match.group(2)
            logger.warning(f"Potential data load risk: Field '{field_name}' in model '{model_name}' is non-nullable {field_type}")
            logger.warning(f"Consider making '{field_name}' nullable (add '?') if CSV might contain empty values or conversion errors")
        
        # Extract relations for bidirectional validation
        relations = []
        relation_matches = re.finditer(r'\s*(\w+)\s+(\w+)\s+@relation\(fields:\s*\[([^\]]+)\],\s*references:\s*\[([^\]]+)\]\)', model_body)
        
        for rel_match in relation_matches:
            field_name = rel_match.group(1)
            target_model = rel_match.group(2)
            source_field = rel_match.group(3).strip()
            target_field = rel_match.group(4).strip()
            
            relations.append({
                'field': field_name,
                'target_model': target_model,
                'source_field': source_field,
                'target_field': target_field
            })
        
        # Also look for array relation fields (e.g., sales Sales[])
        array_relation_matches = re.finditer(r'\s*(\w+)\s+(\w+)\[\]', model_body)
        
        for arr_rel_match in array_relation_matches:
            field_name = arr_rel_match.group(1)
            target_model = arr_rel_match.group(2)
            
            relations.append({
                'field': field_name,
                'target_model': target_model,
                'is_array': True
            })
        
        model_relations[model_name] = relations
    
    # Validate bidirectional relations
    missing_relations = []
    for model_name, relations in model_relations.items():
        for relation in relations:
            if relation.get('is_array', False):
                # This is the "many" side - check if there's a matching "one" side
                target_model = relation['target_model']
                target_relations = model_relations.get(target_model, [])
                    
                # Check if target model has a relation back to this model
                has_reverse = any(
                    rel.get('target_model') == model_name and not rel.get('is_array', False)
                    for rel in target_relations
                )
                    
                if not has_reverse:
                    missing_relations.append(f"Model {target_model} is missing a relation back to {model_name}")
                
            elif 'source_field' in relation:
                # This is the "one" side - check if there's a matching "many" side
                target_model = relation['target_model']
                target_relations = model_relations.get(target_model, [])
                    
                # Check if target model has an array relation back to this model
                has_reverse = any(
                    rel.get('target_model') == model_name and rel.get('is_array', False)
                    for rel in target_relations
                )
                    
                if not has_reverse:
                    missing_relations.append(f"Model {target_model} is missing a relation back to {model_name}")
        
    if missing_relations:
        logger.warning(f"Schema has missing bidirectional relations: {', '.join(missing_relations)}")
        logger.warning("Adding a comment to the schema to alert the user")
            
        # We won't fail validation but will add a warning to the schema itself
            
    logger.info("Basic validation of schema output passed.")
    return True, None

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

def _fix_missing_relations(schema_content: str) -> str:
    """
    Analyzes a Prisma schema for missing bidirectional relations and attempts to fix them.
    
    Args:
        schema_content: The original Prisma schema string
        
    Returns:
        Fixed schema with bidirectional relations added where missing
    """
    logger.info("Checking and fixing missing bidirectional relations in schema...")
    
    # Extract all model blocks
    models = {}
    model_matches = re.finditer(r'model\s+(\w+)\s*{([^}]*)}', schema_content, re.DOTALL)
    
    for model_match in model_matches:
        model_name = model_match.group(1)
        model_body = model_match.group(2)
        models[model_name] = model_body
    
    fixed_models = {}
    
    # First pass: collect all relation information
    relations = {}
    for model_name, model_body in models.items():
        model_relations = []
        
        # Find @relation fields (one-to-many, from the "one" side)
        relation_matches = re.finditer(
            r'\s*(\w+)\s+(\w+)\s+@relation\(fields:\s*\[([^\]]+)\],\s*references:\s*\[([^\]]+)\]\)', 
            model_body
        )
        
        for rel_match in relation_matches:
            field_name = rel_match.group(1)
            target_model = rel_match.group(2)
            source_field = rel_match.group(3).strip()
            target_field = rel_match.group(4).strip()
            
            model_relations.append({
                'field': field_name,
                'target_model': target_model,
                'source_field': source_field,
                'target_field': target_field,
                'type': 'one'
            })
        
        # Find array relation fields (from the "many" side)
        array_relation_matches = re.finditer(r'\s*(\w+)\s+(\w+)\[\]', model_body)
        
        for arr_rel_match in array_relation_matches:
            field_name = arr_rel_match.group(1)
            target_model = arr_rel_match.group(2)
            
            model_relations.append({
                'field': field_name,
                'target_model': target_model,
                'type': 'many'
            })
        
        relations[model_name] = model_relations
    
    # Second pass: find and fix missing relations
    for model_name, model_relations in relations.items():
        for relation in model_relations:
            target_model = relation['target_model']
            
            # Skip if target model doesn't exist
            if target_model not in relations:
                logger.warning(f"Target model {target_model} for relation in {model_name} not found in schema")
                continue
            
            target_relations = relations[target_model]
            
            # Check if there's a reverse relation
            has_reverse = any(
                rel['target_model'] == model_name 
                for rel in target_relations
            )
            
            if not has_reverse:
                # Need to add a reverse relation
                logger.info(f"Adding missing reverse relation from {target_model} to {model_name}")
                
                if relation['type'] == 'one':
                    # Add a "many" relation to the target model
                    # Generate a reasonable field name based on model name (lowercase plural)
                    field_name = model_name.lower()
                    if not field_name.endswith('s'):
                        field_name = f"{field_name}s"
                    
                    # Check field name doesn't already exist
                    field_pattern = re.compile(fr'\s*{field_name}\s+')
                    if field_pattern.search(models[target_model]):
                        # Try alternatives like items, entries, etc.
                        alternatives = [f"{model_name.lower()}Items", f"{model_name.lower()}Entries", f"{model_name.lower()}Records"]
                        for alt in alternatives:
                            alt_pattern = re.compile(fr'\s*{alt}\s+')
                            if not alt_pattern.search(models[target_model]):
                                field_name = alt
                                break
                    
                    # Add new relation field at the end of the model body, before the closing brace
                    new_field = f"\n  {field_name} {model_name}[]"
                    
                    # Update the model body
                    if '}' in models[target_model]:
                        fixed_models[target_model] = models[target_model].replace('}', f"{new_field}\n}}")
                    else:
                        fixed_models[target_model] = f"{models[target_model]}{new_field}\n"
                
                elif relation['type'] == 'many':
                    # We need source and target fields for @relation
                    # This is trickier without knowing the exact relation
                    # For now, let's log a warning and add a comment
                    logger.warning(f"Cannot automatically add one-side relation from {target_model} to {model_name} without field information")
                    comment = f"\n  // TODO: Add reverse relation to {model_name}"
                    
                    # Update the model body
                    if target_model not in fixed_models:
                        fixed_models[target_model] = models[target_model]
                    
                    if '}' in fixed_models[target_model]:
                        fixed_models[target_model] = fixed_models[target_model].replace('}', f"{comment}\n}}")
                    else:
                        fixed_models[target_model] = f"{fixed_models[target_model]}{comment}\n"
    
    # Copy any models that weren't modified
    for model_name, model_body in models.items():
        if model_name not in fixed_models:
            fixed_models[model_name] = model_body
    
    # Reconstruct the schema
    fixed_schema = schema_content
    for model_name, fixed_body in fixed_models.items():
        # Replace the model body
        pattern = re.compile(f'model\\s+{model_name}\\s*{{([^}}]*?)}}', re.DOTALL)
        fixed_schema = pattern.sub(f'model {model_name} {{{fixed_body}}}', fixed_schema)
    
    # Add warning comment if we made changes
    if fixed_models:
        warning = """
// WARNING: Missing bidirectional relations were automatically added.
// Please review the schema carefully before applying.
"""
        # Add comment after generator block
        generator_pattern = re.compile(r'(generator\s+client\s*{[^}]*})', re.DOTALL)
        fixed_schema = generator_pattern.sub(f'\\1\n{warning}', fixed_schema)
    
    return fixed_schema


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

        is_valid, error_msg = _validate_prisma_schema_output(suggested_schema)
        if not is_valid:
            logger.error(f"LLM generated schema failed basic validation: {error_msg}")
            logger.debug(f"Invalid schema attempt:\n{suggested_schema}")
            # Return default schema as fallback
            logger.warning("Using default schema template as fallback")
            return default_schema

        # Fix any missing bidirectional relations
        fixed_schema = _fix_missing_relations(suggested_schema)
        
        # Add warning comments about potential nullable fields to the schema
        suggested_schema_lines = fixed_schema.splitlines()
        warning_comment = """
// WARNING: CSV DATA LOADING CONSIDERATIONS
// If your CSV files contain empty values or strings that can't be converted to numbers,
// consider making fields nullable (add ? to type) or use String type instead of Int/Float
// for fields that might have mixed content.
"""
        # Find where to insert the warning (after generator block, before first model)
        model_index = -1
        for i, line in enumerate(suggested_schema_lines):
            if line.strip().startswith("model "):
                model_index = i
                break
        
        if model_index > 0:
            # Insert warning before the first model
            suggested_schema_lines.insert(model_index, warning_comment)
            fixed_schema = "\n".join(suggested_schema_lines)

        logger.info("Successfully generated and validated schema suggestion.")
        return fixed_schema

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
