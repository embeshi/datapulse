import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import sqlalchemy

from src.data_handling.db_utils import get_sqlalchemy_engine, get_table_summary
from src.prisma_utils.analysis_loader import load_analysis_data, format_analysis_for_context

logger = logging.getLogger(__name__)

def _parse_prisma_schema(schema_path: Path = Path("prisma/schema.prisma")) -> Dict[str, Any]:
    """
    Parses a Prisma schema file and extracts model definitions.
    
    Args:
        schema_path: Path to the schema.prisma file
        
    Returns:
        Dictionary with parsed schema information 
        {
            'models': {
                'ModelName': {
                    'table_name': 'actual_table_name',  # From @@map or lowercase model name
                    'fields': [
                        {'name': 'field_name', 'type': 'type', 'attributes': ['@id', etc]},
                        ...
                    ],
                    'relations': [
                        {'name': 'relation_name', 'references': 'OtherModel', 'fields': [...], 'references_fields': [...]},
                        ...
                    ]
                },
                ...
            }
        }
    """
    logger.info(f"Parsing Prisma schema from {schema_path}")
    
    if not schema_path.exists():
        logger.error(f"Schema file not found at {schema_path}")
        return {'error': f"Schema file not found at {schema_path}"}
    
    try:
        schema_content = schema_path.read_text()
        
        # Parse models using regex (a simple approach)
        schema_data = {'models': {}}
        
        # Extract model blocks
        model_blocks = re.finditer(
            r'model\s+(\w+)\s*{([^}]*)}', 
            schema_content, 
            re.DOTALL
        )
        
        for model_match in model_blocks:
            model_name = model_match.group(1)
            model_body = model_match.group(2)
            
            # Extract table name from @@map directive
            table_name = model_name.lower()  # Default to lowercase model name
            map_match = re.search(r'@@map\s*\(\s*"([^"]+)"\s*\)', model_body)
            if map_match:
                table_name = map_match.group(1)
            
            # Extract fields
            fields = []
            field_matches = re.finditer(
                r'\s*(\w+)\s+(\w+(?:\?)?)(?:\s+([^/\n]*))?', 
                model_body
            )
            
            for field_match in field_matches:
                field_name = field_match.group(1)
                field_type = field_match.group(2)
                field_attrs_str = field_match.group(3) or ""
                
                # Skip relation fields (they start with a capital letter in type)
                if field_type[0].isupper() and not (field_type.startswith('Int') or 
                                                   field_type.startswith('String') or 
                                                   field_type.startswith('Float') or 
                                                   field_type.startswith('Boolean') or 
                                                   field_type.startswith('DateTime')):
                    continue
                
                # Parse field attributes
                attrs = []
                if field_attrs_str:
                    # Extract all attributes including @map
                    attr_matches = re.finditer(r'(@\w+(?:\([^)]*\))?)', field_attrs_str)
                    attrs = [match.group(1) for match in attr_matches]
                
                fields.append({
                    'name': field_name,
                    'type': field_type,
                    'attributes': attrs
                })
            
            # Extract relations (simplified)
            relations = []
            relation_matches = re.finditer(
                r'(\w+)\s+(\w+)(?:\s+@relation\s*\(\s*fields:\s*\[([^\]]+)\]\s*,\s*references:\s*\[([^\]]+)\]\s*\))?', 
                model_body
            )
            
            for rel_match in relation_matches:
                rel_name = rel_match.group(1)
                rel_type = rel_match.group(2)
                
                # Only process if it's a relation (type starts with capital letter and isn't a primitive)
                if rel_type[0].isupper() and not (rel_type.startswith('Int') or 
                                                rel_type.startswith('String') or 
                                                rel_type.startswith('Float') or 
                                                rel_type.startswith('Boolean') or 
                                                rel_type.startswith('DateTime')):
                    fields_str = rel_match.group(3) or ""
                    refs_str = rel_match.group(4) or ""
                    
                    relations.append({
                        'name': rel_name,
                        'references': rel_type,
                        'fields': [f.strip() for f in fields_str.split(',')] if fields_str else [],
                        'references_fields': [f.strip() for f in refs_str.split(',')] if refs_str else []
                    })
            
            schema_data['models'][model_name] = {
                'table_name': table_name,
                'fields': fields,
                'relations': relations
            }
        
        logger.info(f"Successfully parsed schema with {len(schema_data['models'])} models")
        return schema_data
    
    except Exception as e:
        logger.error(f"Error parsing schema file: {e}")
        return {'error': f"Failed to parse schema: {e}"}

def get_prisma_database_context_string(db_uri: str, schema_path: Path = Path("prisma/schema.prisma")) -> str:
    """
    Generates a rich, structured database context string based on the Prisma schema and 
    adds data summaries using SQLAlchemy. Uses a Markdown-like format for better LLM comprehension.
    
    Args:
        db_uri: The SQLAlchemy database URI (e.g., 'sqlite:///analysis.db')
        schema_path: Path to the schema.prisma file
        
    Returns:
        String containing formatted schema and summaries in a structured, information-rich format
    """
    logger.info("Generating enriched database context from Prisma schema...")
    try:
        # Parse Prisma schema
        schema_data = _parse_prisma_schema(schema_path)
        if 'error' in schema_data:
            return f"Error: {schema_data['error']}"
        
        # Get engine for data summaries
        engine = get_sqlalchemy_engine(db_uri)
        
        # Load analysis data if available
        logger.info("Loading dataset analysis data...")
        analysis_data = load_analysis_data()
        if analysis_data:
            logger.info(f"Loaded analysis data for {len(analysis_data)} tables")
        else:
            logger.info("No analysis data found - will use basic schema information only")
        
        # Build context string with both schema info and data summaries
        context_parts = []
        context_parts.append("Database Context:")
        
        for model_name, model_info in schema_data['models'].items():
            table_name = model_info['table_name']
            context_parts.append(f"\n--- Table: {table_name} (Model: {model_name}) ---")
            
            # Add enriched analysis data if available
            if table_name in analysis_data:
                logger.info(f"Including analysis data for {table_name}")
                formatted_analysis = format_analysis_for_context(analysis_data[table_name])
                if formatted_analysis:
                    context_parts.append(formatted_analysis)
            
            # Generate a simple description based on the model name and relations
            model_description = _generate_model_description(model_name, model_info)
            context_parts.append(f"/// {model_description}")
            
            # Identify primary key
            primary_keys = []
            unique_fields = []
            
            for field in model_info['fields']:
                is_primary = any('@id' in attr for attr in field['attributes'])
                is_unique = any('@unique' in attr for attr in field['attributes'])
                
                if is_primary:
                    primary_keys.append(f"{field['name']} ({field['type']})")
                elif is_unique:
                    unique_fields.append(field['name'])
            
            if primary_keys:
                context_parts.append(f"Primary Key: {', '.join(primary_keys)}")
            
            if unique_fields:
                context_parts.append(f"Unique Fields: {', '.join(unique_fields)}")
            
            # Schema part - format fields as a detailed list
            context_parts.append("Columns:")
            for field in model_info['fields']:
                # Get original Prisma type
                field_type = field['type']
                
                # Format attributes
                attrs_str = ""
                if field['attributes']:
                    formatted_attrs = []
                    for attr in field['attributes']:
                        # Clean up attribute format
                        attr = attr.replace('@map("', '@map("').replace('@default(', '@default(')
                        formatted_attrs.append(attr)
                    
                    if formatted_attrs:
                        attrs_str = f" [{' '.join(formatted_attrs)}]"
                
                # Check for @map attribute to find actual DB column name
                db_column_name = field['name']  # Default to field name
                for attr in field['attributes']:
                    map_match = re.search(r'@map\("([^"]+)"\)', attr)
                    if map_match:
                        db_column_name = map_match.group(1)
                        break
                
                # Generate a simple description for the field
                field_description = _generate_field_description(field['name'], field_type, model_name)
                
                # Format the field entry
                field_entry = f"  - {field['name']} ({field_type}){attrs_str}"
                
                # Add DB column name if different
                if db_column_name != field['name']:
                    field_entry += f" [DB: {db_column_name}]"
                
                field_entry += f" /// {field_description}"
                context_parts.append(field_entry)
            
            # Add relation info if present
            if model_info['relations']:
                context_parts.append("Relationships:")
                for relation in model_info['relations']:
                    if relation['fields'] and relation['references_fields']:
                        # Format as "fieldName: Links to TargetModel via [sourceField] -> [targetField]"
                        rel_info = f"  - {relation['name']}: Links to {relation['references']} via " \
                                  f"[{', '.join(relation['fields'])}] -> [{', '.join(relation['references_fields'])}]"
                        context_parts.append(rel_info)
                    elif 'is_array' in relation and relation['is_array']:
                        # Format as "fieldName: List of related TargetModel records"
                        rel_info = f"  - {relation['name']}: List of related {relation['references']} records"
                        context_parts.append(rel_info)
            
            # Data summary part
            try:
                # Use existing get_table_summary with columns info reconstructed
                columns_info = [{'name': field['name'], 'type': field['type']} for field in model_info['fields']]
                summary = get_table_summary(engine, table_name, columns_info)
                
                context_parts.append("Summary:")
                if 'error' in summary:
                    context_parts.append(f"  Error: {summary['error']}")
                else:
                    context_parts.append(f"  Total Rows: {summary.get('row_count', 'N/A')}")
                    if summary.get('row_count', 0) > 0:  # Only show details if table not empty
                        context_parts.append(f"  Null Counts: {summary.get('null_counts', {})}")
                        context_parts.append(f"  Distinct Counts: {summary.get('distinct_counts', {})}")
                        if summary.get('basic_stats'):
                            context_parts.append(f"  Basic Stats (Numeric): {summary.get('basic_stats', {})}")
                        if summary.get('value_counts'):
                            context_parts.append(f"  Top Value Counts (Low Cardinality Text): {summary.get('value_counts', {})}")
            except Exception as e:
                logger.error(f"Error getting summary for table '{table_name}': {e}")
                context_parts.append(f"  Summary Error: {e}")
        
        context_string = "\n".join(context_parts).strip()
        logger.info("Enriched database context string generated successfully.")
        return context_string
    
    except Exception as e:
        logger.error(f"Error generating database context: {e}")
        return f"Error: An unexpected error occurred during context generation: {e}"

def _generate_model_description(model_name: str, model_info: Dict[str, Any]) -> str:
    """Generate a simple description for a model based on its name and structure."""
    # Check if it's a typical model by looking at its name
    model_name_lower = model_name.lower()
    
    if model_name_lower == 'sales' or model_name_lower == 'sale':
        return "Stores individual sales transactions. Links customers and products."
    elif model_name_lower == 'products' or model_name_lower == 'product':
        return "Represents the products available for sale."
    elif model_name_lower == 'customers' or model_name_lower == 'customer':
        return "Stores customer information."
    elif model_name_lower == 'orders' or model_name_lower == 'order':
        return "Contains order information for purchases."
    elif model_name_lower.endswith('inventory'):
        return "Tracks inventory levels and stock information."
    elif model_name_lower.endswith('categories'):
        return "Defines product categories for classification."
    elif model_name_lower.endswith('users'):
        return "Contains user accounts and authentication information."
    elif model_name_lower.endswith('vendors') or model_name_lower.endswith('suppliers'):
        return "Information about vendors/suppliers that provide products."
    else:
        # Generic description based on the table name
        return f"Contains data for {model_name.replace('_', ' ').lower()}."

def _generate_field_description(field_name: str, field_type: str, model_name: str) -> str:
    """Generate a simple description for a field based on its name and type."""
    name_lower = field_name.lower()
    
    # ID fields
    if name_lower.endswith('_id') or name_lower == 'id':
        if name_lower == 'id' or name_lower == f"{model_name.lower()}_id":
            return f"Unique identifier for the {model_name.lower()}"
        else:
            referenced_entity = name_lower.replace('_id', '')
            return f"Foreign key linking to the {referenced_entity} table"
    
    # Common fields
    if name_lower == 'name':
        return f"Name of the {model_name.lower()}"
    elif name_lower == 'description':
        return f"Description of the {model_name.lower()}"
    elif name_lower == 'price' or name_lower == 'unit_price':
        return "Price value"
    elif name_lower == 'amount':
        return "The monetary amount"
    elif name_lower == 'quantity':
        return "Quantity value"
    elif name_lower == 'email':
        return "Email address"
    elif name_lower == 'phone' or name_lower == 'phone_number':
        return "Phone number"
    elif name_lower == 'address':
        return "Physical address"
    elif name_lower == 'city':
        return "City name"
    elif name_lower == 'state' or name_lower == 'province':
        return "State or province"
    elif name_lower == 'country':
        return "Country name"
    elif name_lower == 'postal_code' or name_lower == 'zip_code':
        return "Postal or ZIP code"
    elif name_lower == 'status':
        return "Status indicator"
    elif name_lower.endswith('_date') or name_lower == 'date':
        date_type = name_lower.replace('_date', '')
        if date_type:
            return f"Date of {date_type}"
        else:
            return "Date value"
    elif name_lower == 'created_at' or name_lower == 'created_date':
        return "When the record was created"
    elif name_lower == 'updated_at' or name_lower == 'updated_date':
        return "When the record was last updated"
    elif name_lower == 'deleted_at' or name_lower == 'deleted_date':
        return "When the record was deleted (for soft deletes)"
    elif name_lower == 'is_active' or name_lower == 'active':
        return "Whether the record is active"
    elif name_lower == 'category' or name_lower == 'category_name':
        return "Category classification"
    elif name_lower == 'notes' or name_lower == 'comments':
        return "Additional notes or comments"
    
    # Generic description based on the field name and type
    field_base_name = name_lower.replace('_', ' ')
    
    # Handle specific data types
    if field_type.startswith('DateTime'):
        return f"Timestamp for {field_base_name}"
    elif field_type.startswith('Boolean'):
        return f"Flag indicating {field_base_name}"
    elif field_type.endswith('?'):
        return f"Optional {field_base_name}"
    else:
        return f"The {field_base_name} value"
