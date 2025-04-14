import pandas as pd
import json
import logging
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
    logger.info(f"Analyzing dataset: {table_name}")
    
    # Basic dataset info
    analysis = {
        "table_name": table_name,
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {}
    }
    
    # Analyze each column
    for column in df.columns:
        col_analysis = analyze_column(df, column)
        analysis["columns"][column] = col_analysis
    
    # Get LLM descriptions for columns
    descriptions = get_column_descriptions(df, table_name)
    
    # Add descriptions to the analysis
    for column, description in descriptions.items():
        if column in analysis["columns"]:
            analysis["columns"][column]["description"] = description
    
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
    logger.info(f"Generating column descriptions for table: {table_name}")
    
    # Create sample data for the LLM
    sample_rows = df.head(5).to_dict(orient='records')
    
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
    
    try:
        response = client.call_llm(prompt)
        # Try to extract JSON from the response
        try:
            # Find JSON-like content between curly braces
            import re
            json_match = re.search(r'{.*}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                descriptions = json.loads(json_str)
                return descriptions
            else:
                logger.warning(f"Could not extract JSON from LLM response: {response}")
                return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse column descriptions JSON: {e}")
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
    
    for table_name, csv_path in csv_mapping.items():
        try:
            logger.info(f"Loading and analyzing {csv_path} for table '{table_name}'")
            df = pd.read_csv(csv_path)
            
            # Perform analysis
            analysis = analyze_dataset(df, table_name)
            
            # Save analysis
            file_path = output_path / f"{table_name}_analysis.json"
            success = save_analysis_to_file(analysis, file_path)
            
            results[table_name] = success
            if success:
                logger.info(f"Successfully analyzed {table_name} and saved to {file_path}")
            else:
                logger.error(f"Failed to save analysis for {table_name}")
        
        except Exception as e:
            logger.error(f"Failed to analyze {csv_path} for table '{table_name}': {e}")
            results[table_name] = False
    
    return results

def prompt_and_analyze_datasets(csv_mapping: Dict[str, Union[str, Path]]) -> None:
    """
    Prompt the user to run dataset analysis and execute if confirmed.
    
    Args:
        csv_mapping: Dictionary mapping table names to CSV file paths
    """
    try:
        print("\n=== Dataset Analysis ===")
        print(f"Would you like to run an initial dataset analysis on the {len(csv_mapping)} tables?")
        print("This will generate statistics and infer column descriptions using AI.")
        confirmation = input("Run dataset analysis? (y/N): ").strip().lower()
        
        if confirmation == 'y':
            logger.info(f"User confirmed dataset analysis for {len(csv_mapping)} tables")
            results = analyze_tables_from_csv(csv_mapping)
            
            # Report results
            success_count = sum(1 for success in results.values() if success)
            print(f"\nAnalysis complete: {success_count}/{len(csv_mapping)} tables analyzed successfully.")
            print(f"Results saved to the 'analysis_results' directory.")
            
            if success_count < len(csv_mapping):
                failed_tables = [table for table, success in results.items() if not success]
                print(f"Tables that could not be analyzed: {', '.join(failed_tables)}")
        else:
            logger.info("User declined dataset analysis")
            print("Dataset analysis skipped.")
    
    except Exception as e:
        logger.error(f"Error during dataset analysis prompt/execution: {e}")
        print(f"\nERROR: Dataset analysis failed: {e}")
