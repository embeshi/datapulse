from typing import List, Dict, Any
import json # For potentially formatting results/context

# Helper function to format results safely for prompts
def _format_results_for_prompt(
    results: List[Dict],
    max_rows: int = 5,
    max_total_chars: int = 1000 # Limit total characters to prevent huge prompts
    ) -> str:
    """Formats a list of result dictionaries into a string suitable for an LLM prompt."""
    if not results:
        return "Query returned no results."

    limited_results = results[:max_rows]
    try:
        # Try pretty printing JSON for readability if results are simple
        results_str = json.dumps(limited_results, indent=2)
    except TypeError:
        # Fallback to simple string conversion if JSON fails
        results_str = "\n".join(str(row) for row in limited_results)

    if len(results_str) > max_total_chars:
        results_str = results_str[:max_total_chars] + "\n... (results truncated)"

    header = f"Query returned {len(results)} row(s). Showing first {len(limited_results)}:"
    return f"{header}\n{results_str}"


def get_planning_prompt(user_request: str, database_context: str) -> str: # Changed db_schema to database_context
    """
    Generates the prompt for the Planning Agent LLM call.

    Args:
        user_request: The user's original natural language request.
        database_context: String containing schema and data summaries.

    Returns:
        The formatted prompt string.
    """
    prompt = f"""
You are an expert data analyst acting as a planner. Your role is to understand a user's request
and, based on the provided database context (schema and summaries), create a clear, logical,
step-by-step conceptual plan describing the SQL operations needed to fulfill the request.
Use the data summaries (row counts, nulls, distinct values, stats) to make informed decisions
about potential joins, filters, and aggregations. Do NOT write the SQL itself.

USER REQUEST:
"{user_request}"

DATABASE CONTEXT:
{database_context}

CRITICAL INSTRUCTIONS:
1. ONLY use tables and columns that are explicitly mentioned in the DATABASE CONTEXT above.
2. DO NOT make assumptions about tables or relationships that are not documented in the context.
3. If the request requires tables or data that are not available in the context, your plan should
   acknowledge this limitation and suggest what can be accomplished with the available data only.
4. Be realistic about what analysis is possible with the tables provided.

Based on the request and the database context, provide a numbered, conceptual plan outlining
the database operations needed. Focus on *what* needs to be done with the available tables.

PLAN:
"""
    return prompt.strip()


def get_sql_generation_prompt(conceptual_plan: str, database_context: str) -> str: # Changed db_schema to database_context
    """
    Generates the prompt for the SQL Generation Agent LLM call.

    Args:
        conceptual_plan: The step-by-step plan generated by the Planner Agent.
        database_context: String containing schema and data summaries.

    Returns:
        The formatted prompt string.
    """
    prompt = f"""
You are an expert SQL Coder, specifically for SQLite. Your task is to translate a conceptual
analysis plan into a single, executable SQLite SQL query. Use the provided database context
(schema and summaries) for table/column names and to potentially optimize the query
(e.g., understanding data distribution from summaries).

DATABASE CONTEXT:
{database_context}

CONCEPTUAL PLAN:
{conceptual_plan}

CRITICAL INSTRUCTIONS:
1. ONLY use tables and columns that explicitly appear in the DATABASE CONTEXT above.
2. When the context shows a column with both a database name and a Prisma name like "product_id (INTEGER) [Prisma: productId]", 
   ALWAYS use the database column name (product_id) in your SQL queries, NOT the Prisma field name.
3. If analysis data is available (information starting with "Analysis for..."), pay close attention to the 
   column descriptions, data types, distributions, and sample values. Use this to write more accurate queries.
   If no analysis data is present, rely on the schema information and summaries provided.
   When available, analysis data helps you:
   - Choose appropriate JOIN types based on null count percentages
   - Set proper filter conditions based on actual data ranges and sample values
   - Optimize queries by leveraging column cardinality information
   - Handle potential null values appropriately
4. DO NOT assume or infer the existence of any tables not listed in the DATABASE CONTEXT.
5. If the plan assumes tables that don't exist in the context, modify your approach to work with ONLY the available tables.
6. If you cannot fulfill the request with the available tables, return a clear error message as a SQL comment: "-- ERROR: Cannot complete request. Required table X is missing."

Generate the SQLite SQL query that accurately implements the conceptual plan.
IMPORTANT: Output ONLY the SQL query string, without any explanation, comments,
or surrounding text (e.g., no "```sql" markers). Ensure correct quoting for identifiers if needed.

SQL QUERY:
"""
    return prompt.strip()

def get_interpretation_prompt(user_request: str, results: List[Dict[str, Any]]) -> str:
    """
    Generates the prompt for the Interpreter Agent LLM call.

    Args:
        user_request (str): The user's original natural language request.
        results (List[Dict[str, Any]]): The data returned from the SQL execution.

    Returns:
        str: The formatted prompt string.
    """
    formatted_results = _format_results_for_prompt(results)

    prompt = f"""
You are a helpful data analyst assistant. You need to interpret query results and explain
them clearly to a non-technical user in the context of their original request.

USER REQUEST:
"{user_request}"

QUERY RESULTS:
{formatted_results}

Based on the user's request and the query results provided, write a concise, easy-to-understand
natural language summary of the findings. Focus on answering the user's question directly.
Do not just repeat the data; explain what it means.

SUMMARY:
"""
    return prompt.strip()

def get_sql_debug_prompt(user_request: str, failed_sql: str, error_message: str, 
                          conceptual_plan: str, database_context: str) -> str:
    """
    Generates the prompt for the SQL Debugging Agent LLM call when SQL execution fails.

    Args:
        user_request: The user's original natural language request.
        failed_sql: The SQL query that failed execution.
        error_message: The database error message received.
        conceptual_plan: The original conceptual plan that led to the SQL.
        database_context: String containing schema and data summaries.

    Returns:
        The formatted prompt string.
    """
    prompt = f"""
You are an expert SQL debugger specializing in SQLite. Your task is to analyze a failed SQL query,
understand the error message, and provide a corrected version of the query that will execute successfully.

USER REQUEST:
"{user_request}"

ORIGINAL CONCEPTUAL PLAN:
{conceptual_plan}

DATABASE CONTEXT:
{database_context}

FAILED SQL QUERY:
{failed_sql}

ERROR MESSAGE:
{error_message}

ANALYSIS INSTRUCTIONS:
1. Carefully examine the error message to identify the specific issue.
2. Common SQLite errors include:
   - Syntax errors: Incorrect SQL syntax or reserved word issues
   - Table/column not found: Referencing tables or columns that don't exist
   - Type mismatch: Attempting operations between incompatible data types
   - Constraint violations: Violating primary key, foreign key, or other constraints
3. Check if table and column names in the query match exactly what's in the DATABASE CONTEXT.
4. Ensure proper quoting of identifiers if they contain special characters or are SQLite keywords.
5. Verify join conditions refer to columns of the correct type.

CRITICAL REQUIREMENTS:
1. You MUST provide a corrected SQL query that adheres strictly to SQLite syntax.
2. The corrected SQL must maintain the intent of the original query and conceptual plan.
3. ONLY use tables and columns that explicitly appear in the DATABASE CONTEXT.
4. Add brief inline comments (-- comment) explaining your key fixes.
5. If multiple solutions are possible, choose the simplest approach.
6. If the error is unfixable (e.g., requested data simply doesn't exist in schema), clearly state why.

Provide your corrected SQL query below:
"""
    return prompt.strip()

def get_schema_suggestion_prompt(csv_samples: Dict[str, str]) -> str:
    """
    Generates the prompt for the LLM to suggest a Prisma schema.

    Args:
        csv_samples: Dictionary mapping filename to string containing headers and sample rows.

    Returns:
        The formatted prompt string.
    """
    sample_texts = []
    for filename, content in csv_samples.items():
        sample_texts.append(f"-- Start Sample: {filename} --\n{content}\n-- End Sample: {filename} --")

    all_samples_text = "\n\n".join(sample_texts)

    prompt = f"""
You are an expert database schema designer specializing in Prisma schema syntax for SQLite.
Analyze the following CSV samples (headers and first few data rows) provided by the user.
Your goal is to generate a *suggested* `schema.prisma` file content.

RULES:
1. Infer table names from the filenames (e.g., 'sales.csv' -> model Sales). Use PascalCase for model names. ALWAYS include `@@map("original_filename_base")` to ensure the actual table name matches the CSV filename base exactly.
2. Infer column names from the CSV headers. Use camelCase or snake_case for field names. Use `@map("Original Header")` if the field name significantly differs from the header.
3. Infer appropriate Prisma data types compatible with SQLite: `String`, `Int`, `Float`, `Boolean`, `DateTime`. Be conservative: use `String` if type is ambiguous, mixed, or format is unclear. For dates/times, suggest `DateTime` if format looks standard (like ISO 8601 or YYYY-MM-DD HH:MM:SS), otherwise use `String`.
4. Identify potential primary keys (usually columns named 'id', 'xxx_id'). Mark the best candidate with `@id @default(autoincrement())` if it looks like a sequential integer, or just `@id` if it's another type (like a string UUID - though less common in CSVs). If no clear ID exists, let Prisma handle it or don't add `@id`.
5. Identify potential optional fields (columns with empty strings or many missing values in samples) and mark the type with `?` (e.g., `String?`).
6. For relationships between tables: ALWAYS define BOTH sides of every relation:
   - When table A references table B (e.g., with a column like product_id), define:
     a) In table A: Include a relation field TO table B (e.g., `product Products @relation(fields: [productId], references: [productId])`)
     b) In table B: Include a matching relation field back TO table A (e.g., `sales Sales[]`) that references table A
   - This bidirectional relationship is REQUIRED by Prisma, not optional
   - For one-to-many relationships (most common in CSV data), use type syntax with [] on the "many" side (e.g., `sales Sales[]`)
7. Format the output STRICTLY as the content of a `schema.prisma` file.
8. Include the standard `datasource db` block for SQLite, pointing to `env("DATABASE_URL")`.
9. Include the standard `generator client` block specifying `provider = "prisma-client-py"`.
10. Do NOT include any explanations, apologies, or text outside the schema definition itself. This output will be saved directly to a file.
11. IMPORTANT: ALWAYS include `@@map("filename_base")` for every model to ensure exact table name matching with original CSV names. Example: for customers.csv, use: @@map("customers")

CSV SAMPLES:
{all_samples_text}

Generate the suggested `schema.prisma` content below:

```prisma
// Datasource and Generator Blocks
datasource db {{
  provider = "sqlite"
  url      = env("DATABASE_URL")
}}

generator client {{
  provider = "prisma-client-py"
  // interface = "asyncio" // Optional: uncomment if needed
}}

// Inferred Models Below
```
"""
    # The ```prisma block helps guide the LLM output format
    return prompt.strip()

# Example Usage
if __name__ == "__main__":

    print("--- Testing Prompt Generation ---")
    test_schema = """
Table: sales
  Columns: sale_id (INTEGER), product_id (INTEGER), amount (FLOAT), sale_date (TEXT)

Table: products
  Columns: product_id (INTEGER), name (TEXT), category (TEXT)
""".strip()

    test_context = """
Database Context:
-- Table: sales --
  Schema Columns: sale_id (INTEGER), product_id (INTEGER), amount (FLOAT), sale_date (TEXT)
  Summary:
    Total Rows: 1000
    Null Counts: {'sale_id': 0, 'product_id': 5, 'amount': 2, 'sale_date': 0}
    Distinct Counts: {'sale_id': 1000, 'product_id': 55, 'amount': 850, 'sale_date': 90}
    Basic Stats (Numeric): {'sale_id': {'min': 1, 'max': 1000, 'avg': 500.5}, 'product_id': {'min': 101, 'max': 155, 'avg': 125.3}, 'amount': {'min': 1.5, 'max': 500.0, 'avg': 75.2}}

-- Table: products --
  Schema Columns: product_id (INTEGER), name (TEXT), category (TEXT)
  Summary:
    Total Rows: 55
    Null Counts: {'product_id': 0, 'name': 0, 'category': 1}
    Distinct Counts: {'product_id': 55, 'name': 55, 'category': 6}
    Top Value Counts (Low Cardinality Text): {'category': {'Electronics': 20, 'Clothing': 15, 'Home': 10, 'Books': 5, 'NULL': 1, 'Toys': 4}}
""".strip()
    test_request = "Show me the total sales amount for each product category, ignoring products without a category."
    test_plan = """
1. Filter the 'products' table to exclude rows where 'category' is NULL.
2. Join the filtered 'products' table with the 'sales' table on 'product_id'.
3. Group the results by product 'category'.
4. Calculate the sum of the 'amount' for each category.
5. Select the category and the total sales amount.
""".strip()
    test_results = [
        {'category': 'Electronics', 'total_sales': 1575.50},
        {'category': 'Clothing', 'total_sales': 850.00},
    ]
    test_results_empty = []

    # Test Planner Prompt
    planner_prompt = get_planning_prompt(test_request, test_schema)
    print("\n--- PLANNER PROMPT ---")
    print(planner_prompt)
    print("----------------------")

    # Test SQL Generator Prompt
    sql_gen_prompt = get_sql_generation_prompt(test_plan, test_schema)
    print("\n--- SQL GENERATOR PROMPT ---")
    print(sql_gen_prompt)
    print("--------------------------")

    # Test Interpreter Prompt (with results)
    interpreter_prompt = get_interpretation_prompt(test_request, test_results)
    print("\n--- INTERPRETER PROMPT (Results) ---")
    print(interpreter_prompt)
    print("-----------------------------------")

    # Test Interpreter Prompt (empty results)
    interpreter_prompt_empty = get_interpretation_prompt(test_request, test_results_empty)
    print("\n--- INTERPRETER PROMPT (Empty) ---")
    print(interpreter_prompt_empty)
    print("---------------------------------")
    
    # Test Schema Suggestion Prompt (commented out since it would be lengthy)
    # csv_samples = {
    #    "products.csv": "Headers:\nproduct_id,name,category,price\n\nSample Data:\n101,Laptop,Electronics,999.99\n102,T-shirt,Clothing,19.99"
    # }
    # schema_prompt = get_schema_suggestion_prompt(csv_samples)
    # print("\n--- SCHEMA SUGGESTION PROMPT ---")
    # print(schema_prompt)
    # print("--------------------------------")



