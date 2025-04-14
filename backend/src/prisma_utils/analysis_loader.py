import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

def load_analysis_data(analysis_dir: str = "analysis_results") -> Dict[str, Any]:
    """
    Load analysis data from JSON files in the specified directory.
    
    Args:
        analysis_dir: Path to the directory containing analysis JSON files
        
    Returns:
        Dictionary mapping table names to their analysis data
    """
    result = {}
    analysis_path = Path(analysis_dir)
    
    if not analysis_path.exists() or not analysis_path.is_dir():
        logger.warning(f"Analysis directory not found: {analysis_dir}")
        return result
    
    for file_path in analysis_path.glob("*_analysis.json"):
        try:
            with open(file_path, 'r') as f:
                analysis_data = json.load(f)
                
            if "table_name" in analysis_data:
                table_name = analysis_data["table_name"]
                result[table_name] = analysis_data
                logger.info(f"Loaded analysis data for table: {table_name}")
            else:
                logger.warning(f"Analysis file {file_path} missing table_name field")
        except Exception as e:
            logger.error(f"Error loading analysis file {file_path}: {e}")
    
    logger.info(f"Loaded analysis data for {len(result)} tables")
    return result

def format_analysis_for_context(analysis_data: Dict[str, Any]) -> str:
    """
    Format the analysis data into a string suitable for inclusion in the database context.
    
    Args:
        analysis_data: The analysis data dictionary for a single table
        
    Returns:
        Formatted string with key analysis insights
    """
    if not analysis_data:
        return ""
    
    table_name = analysis_data.get("table_name", "unknown_table")
    row_count = analysis_data.get("row_count", 0)
    column_count = analysis_data.get("column_count", 0)
    
    lines = [f"Analysis for {table_name} ({row_count} rows, {column_count} columns):"]
    
    # Add column-specific insights
    columns_data = analysis_data.get("columns", {})
    for col_name, col_info in columns_data.items():
        # Include description if available
        description = col_info.get("description", "")
        if description:
            lines.append(f"  - {col_name}: {description}")
        
        # Include data type and important stats
        data_type = col_info.get("data_type", "unknown")
        null_pct = col_info.get("null_percentage", 0)
        unique_count = col_info.get("unique_count", 0)
        
        stats = f"Type: {data_type}"
        if null_pct > 0:
            stats += f", {null_pct:.1f}% null"
        if unique_count > 0:
            stats += f", {unique_count} unique values"
        
        lines.append(f"    {stats}")
        
        # Include sample values for object/string types
        if "sample_values" in col_info and col_info["sample_values"]:
            sample_str = ", ".join([str(s) for s in col_info["sample_values"][:5]])
            if len(col_info["sample_values"]) > 5:
                sample_str += ", ..."
            lines.append(f"    Sample values: {sample_str}")
        
        # Include numeric stats if available
        if "mean" in col_info and "min" in col_info and "max" in col_info:
            lines.append(f"    Range: {col_info['min']} to {col_info['max']}, avg: {col_info['mean']:.2f}")
        
        # Include value counts for categorical data
        if "value_counts" in col_info and col_info["value_counts"]:
            counts_str = ", ".join([f"{k}: {v}" for k, v in col_info["value_counts"].items()][:5])
            if len(col_info["value_counts"]) > 5:
                counts_str += ", ..."
            lines.append(f"    Distribution: {counts_str}")
    
    return "\n".join(lines)
