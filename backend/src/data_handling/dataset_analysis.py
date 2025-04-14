import pandas as pd
import json
import logging
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import numpy as np
from src.llm import client

logger = logging.getLogger(__name__)

def analyze_dataset(df: pd.DataFrame, table_name: str) -> Dict[str, Any]:
    """
    Perform comprehensive analysis on a dataset.
    
    Args:
        df: Pandas DataFrame to analyze
        table_name: Name of the table/dataset
        
    Returns:
        Dictionary containing analysis results
    """
    logger.info(f"Starting full analysis of dataset: {table_name} with {len(df)} rows and {len(df.columns)} columns")
    
    # Basic dataset info
    analysis = {
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {}
    }
    
    # Analyze each column
    logger.info(f"Analyzing {len(df.columns)} columns for dataset: {table_name}")
    for i, column in enumerate(df.columns):
        logger.info(f"[{i+1}/{len(df.columns)}] Analyzing column: {column} ({df[column].dtype})")
        col_analysis = analyze_column(df, column)
        analysis["columns"][column] = col_analysis
    
    # Get LLM descriptions for columns
    logger.info(f"Generating LLM descriptions for columns in: {table_name}")
    descriptions = get_column_descriptions(df, table_name)
    logger.info(f"Received descriptions for {len(descriptions)} columns")
    
    # Add descriptions to the analysis
    for column, description in descriptions.items():
        if column in analysis["columns"]:
            analysis["columns"][column]["description"] = description
    
    logger.info(f"Dataset analysis completed for: {table_name}")
    return analysis

def analyze_column(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    """
    Analyze a single column in the dataset.
    
    Args:
        df: Pandas DataFrame
        column: Column name to analyze
        
    Returns:
        Dictionary with column analysis
    """
    col_data = df[column]
    
    # Basic stats
    result = {
        "data_type": str(col_data.dtype),
        "null_count": int(col_data.isna().sum()),
        "null_percentage": float(col_data.isna().mean() * 100),
        "unique_count": int(col_data.nunique())
    }
    
    # Add sample values for object type columns
    if str(col_data.dtype) == "object":
        # Get up to 10 unique sample values
        unique_samples = col_data.dropna().unique()[:10]
        # Convert to strings and add to result
        result["sample_values"] = [str(val) for val in unique_samples]
    
    # Handle different data types
    if pd.api.types.is_numeric_dtype(col_data):
        # Numeric column
        result.update({
            "min": float(col_data.min()) if not pd.isna(col_data.min()) else None,
            "max": float(col_data.max()) if not pd.isna(col_data.max()) else None,
            "mean": float(col_data.mean()) if not pd.isna(col_data.mean()) else None,
            "median": float(col_data.median()) if not pd.isna(col_data.median()) else None,
            "std": float(col_data.std()) if not pd.isna(col_data.std()) else None,
            "percentiles": {
                "5%": float(np.percentile(col_data.dropna(), 5)) if len(col_data.dropna()) > 0 else None,
                "25%": float(np.percentile(col_data.dropna(), 25)) if len(col_data.dropna()) > 0 else None,
                "50%": float(np.percentile(col_data.dropna(), 50)) if len(col_data.dropna()) > 0 else None,
                "75%": float(np.percentile(col_data.dropna(), 75)) if len(col_data.dropna()) > 0 else None,
                "95%": float(np.percentile(col_data.dropna(), 95)) if len(col_data.dropna()) > 0 else None
            }
        })
    elif pd.api.types.is_string_dtype(col_data) or pd.api.types.is_categorical_dtype(col_data):
        # Text or categorical column
        if result["unique_count"] <= 25:  # Only show value counts for low cardinality
            value_counts = col_data.value_counts().head(10).to_dict()
            # Convert keys to strings in case they're not
            result["value_counts"] = {str(k): int(v) for k, v in value_counts.items()}
            
        # Text stats if string type
        if pd.api.types.is_string_dtype(col_data):
            non_null_values = col_data.dropna()
            if len(non_null_values) > 0:
                result["avg_length"] = float(non_null_values.str.len().mean())
                result["min_length"] = int(non_null_values.str.len().min())
                result["max_length"] = int(non_null_values.str.len().max())
    
    elif pd.api.types.is_datetime64_dtype(col_data):
        # Date/time column
        if len(col_data.dropna()) > 0:
            result.update({
                "min_date": col_data.min().isoformat() if not pd.isna(col_data.min()) else None,
                "max_date": col_data.max().isoformat() if not pd.isna(col_data.max()) else None,
                "date_range_days": (col_data.max() - col_data.min()).days if not pd.isna(col_data.min()) and not pd.isna(col_data.max()) else None
            })
    
    return result

def get_column_descriptions(df: pd.DataFrame, table_name: str) -> Dict[str, str]:
    """
    Use LLM to generate meaningful descriptions for each column.
    
    Args:
        df: Pandas DataFrame
        table_name: Name of the table
        
    Returns:
        Dictionary mapping column names to descriptions
    """
    logger.info(f"Starting LLM column description generation for table: {table_name}")
    
    # Create sample data for the LLM
    sample_rows = df.head(5).to_dict(orient='records')
    logger.info(f"Prepared sample data with {len(sample_rows)} rows for LLM prompt")
    
    # Format the prompt for the LLM
    prompt = f"""
You are a data analyst helping to document a dataset. I'll provide information about a table
and a sample of its data. Please generate concise, meaningful descriptions for each column.

TABLE NAME: {table_name}

COLUMNS:
{', '.join(df.columns)}

SAMPLE DATA (first 5 rows):
{json.dumps(sample_rows, indent=2)}

For each column, provide:
1. A brief description of what the data appears to represent
2. Any patterns or notable characteristics
3. The business/domain meaning if you can infer it

Format your answer as a JSON object with column names as keys and descriptions as values.
Example format: {{"column_name": "This column represents..."}}
"""
    logger.debug(f"Generated LLM prompt of {len(prompt)} characters")
    
    try:
        logger.info(f"Calling LLM to generate descriptions for {len(df.columns)} columns")
        response = client.call_llm(prompt)
        logger.info(f"Received LLM response of {len(response)} characters")
        
        # Try to extract JSON from the response
        try:
            # Find JSON-like content between curly braces
            import re
            json_match = re.search(r'{.*}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                descriptions = json.loads(json_str)
                logger.info(f"Successfully extracted descriptions for {len(descriptions)} columns")
                return descriptions
            else:
                logger.warning(f"Could not extract JSON from LLM response: {response[:200]}...")
                return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse column descriptions JSON: {e}")
            logger.error(f"Raw response excerpt: {response[:200]}...")
            return {}
    except Exception as e:
        logger.error(f"Failed to generate column descriptions: {e}")
        return {}

def save_analysis_to_file(analysis: Dict[str, Any], output_path: Union[str, Path]) -> bool:
    """
    Save the analysis results to a JSON file.
    
    Args:
        analysis: Analysis results dictionary
        output_path: Path to save the analysis file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(analysis, f, indent=2)
        
        logger.info(f"Analysis saved to {output_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save analysis to {output_path}: {e}")
        return False

def analyze_tables_from_csv(
    csv_mapping: Dict[str, Union[str, Path]], 
    output_dir: Union[str, Path] = "analysis_results"
) -> Dict[str, bool]:
    """
    Analyze multiple CSV files and save analysis results.
    
    Args:
        csv_mapping: Dictionary mapping table names to CSV file paths
        output_dir: Directory to save analysis results
        
    Returns:
        Dictionary mapping table names to success status
    """
    results = {}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Starting analysis of {len(csv_mapping)} tables, results will be saved to {output_path}")
    
    for i, (table_name, csv_path) in enumerate(csv_mapping.items()):
        try:
            logger.info(f"[{i+1}/{len(csv_mapping)}] Loading and analyzing {csv_path} for table '{table_name}'")
            df = pd.read_csv(csv_path)
            logger.info(f"Successfully loaded {len(df)} rows and {len(df.columns)} columns from {csv_path}")
            
            # Perform analysis
            analysis = analyze_dataset(df, table_name)
            
            # Save analysis
            file_path = output_path / f"{table_name}_analysis.json"
            logger.info(f"Saving analysis results to {file_path}")
            success = save_analysis_to_file(analysis, file_path)
            
            results[table_name] = success
            if success:
                logger.info(f"Successfully analyzed {table_name} and saved to {file_path}")
            else:
                logger.error(f"Failed to save analysis for {table_name}")
        
        except Exception as e:
            logger.error(f"Failed to analyze {csv_path} for table '{table_name}': {e}")
            logger.error(traceback.format_exc())
            results[table_name] = False
    
    logger.info(f"Completed analysis of {len(csv_mapping)} tables with {sum(results.values())} successes")
    return results

def prompt_and_analyze_datasets(csv_mapping: Dict[str, Union[str, Path]]) -> None:
    """
    Prompt the user to run dataset analysis and execute if confirmed.
    
    Args:
        csv_mapping: Dictionary mapping table names to CSV file paths
    """
    try:
        print("\n=== Dataset Analysis ===")
        logger.info(f"Prompting user to run dataset analysis on {len(csv_mapping)} tables")
        print(f"Would you like to run an initial dataset analysis on the {len(csv_mapping)} tables?")
        print("This will generate statistics and infer column descriptions using AI.")
        confirmation = input("Run dataset analysis? (y/N): ").strip().lower()
        
        if confirmation == 'y':
            logger.info(f"User confirmed dataset analysis for {len(csv_mapping)} tables")
            print("\nStarting dataset analysis...")
            print(f"This will analyze {len(csv_mapping)} tables: {', '.join(csv_mapping.keys())}")
            
            results = analyze_tables_from_csv(csv_mapping)
            
            # Report results
            success_count = sum(1 for success in results.values() if success)
            logger.info(f"Analysis complete: {success_count}/{len(csv_mapping)} tables analyzed successfully")
            print(f"\nAnalysis complete: {success_count}/{len(csv_mapping)} tables analyzed successfully.")
            print(f"Results saved to the 'analysis_results' directory.")
            
            if success_count < len(csv_mapping):
                failed_tables = [table for table, success in results.items() if not success]
                logger.warning(f"Failed to analyze tables: {', '.join(failed_tables)}")
                print(f"Tables that could not be analyzed: {', '.join(failed_tables)}")
        else:
            logger.info("User declined dataset analysis")
            print("Dataset analysis skipped.")
    
    except Exception as e:
        logger.error(f"Error during dataset analysis prompt/execution: {e}")
        logger.error(traceback.format_exc())
        print(f"\nERROR: Dataset analysis failed: {e}")
