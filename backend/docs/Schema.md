# DataWeave AI: Prisma Schema Generation and Workflow Specification

**Version:** 1.1
**Date:** 2025-04-15

## 1. Overview

This document outlines the process for defining and establishing the database schema used by the DataWeave AI analysis engine. The system utilizes **Prisma** as its primary ORM, schema definition tool, and migration manager, targeting a **SQLite** database (typically `analysis.db`).

To handle potentially unstructured user-provided CSV data, a **hybrid schema generation approach** is employed:

1.  An **LLM suggests** an initial `schema.prisma` based on sampling input CSV files (`src/schema_generator/suggest.py`).
2.  The **user reviews, potentially edits, and confirms** this suggested schema (currently a manual step after running `scripts/generate_schema.py`).
3.  The user-confirmed schema (`prisma/schema.prisma`) is then used by Prisma CLI commands (`prisma generate`, `prisma db push`) to **set up the database structure**.
4.  Finally, data is **loaded** into the established tables using pandas and SQLAlchemy (`src/data_handling/loader.py`).

This approach leverages the LLM's ability to quickly draft a schema while ensuring correctness through mandatory user oversight before database modifications occur. The final `prisma/schema.prisma` becomes the single source of truth for the database structure.

## 2. Workflow Steps (Implemented via `scripts/generate_schema.py`)

1.  **User Provides Data:** User places input CSV files into the `backend/data/` directory (or specifies paths).
2.  **CSV Sampling (`src/schema_generator/sampler.py`):** The script reads headers and the first N rows (e.g., 10) from each specified CSV file.
3.  **LLM Schema Suggestion (`src/schema_generator/suggest.py`):**
    *   Sampled data is formatted into a prompt (`get_schema_suggestion_prompt`).
    *   The LLM (`src/llm/client.py`) is called to generate suggested `schema.prisma` content.
    *   Basic validation and relation fixing (`_validate_prisma_schema_output`, `_fix_missing_relations`) are attempted on the LLM output.
4.  **Save Suggestion & User Review (Manual Step):**
    *   The script saves the LLM's suggested schema to a temporary file (e.g., `suggested_schema.prisma`).
    *   **Crucially, the script pauses and instructs the user to manually review, edit (if necessary), and save the final desired schema content into `prisma/schema.prisma`.**
5.  **Generate Prisma Client:** After user confirmation (pressing Enter in the script), `prisma generate` is executed via `subprocess` to update the type-safe Python client based on the (now user-confirmed) `prisma/schema.prisma`.
6.  **Setup Database Schema:** `prisma db push --accept-data-loss` is executed via `subprocess` to synchronize the SQLite database structure (`analysis.db`, path defined by `DATABASE_URL` in `.env`) with `prisma/schema.prisma`.
7.  **Load Data (`src/data_handling/loader.py`):** Data from the original CSV files is loaded into the corresponding tables in the now-structured SQLite database using pandas `read_csv` and SQLAlchemy `to_sql`.
8.  **(Optional) Dataset Analysis (`src/data_handling/dataset_analysis.py`):** The user can optionally run a deeper analysis (stats, LLM descriptions) on the loaded data, saving results to `analysis_results/`. This analysis data can later enrich the context provided to agents.
9.  **Analysis Ready:** The system is now ready for the main analysis workflow, using the context derived from the user-confirmed schema and potentially enriched by dataset analysis results.

## 3. Components Involved

| Component                       | Location                            | Responsibility                                                                                                | Type          |
| :------------------------------ | :---------------------------------- | :------------------------------------------------------------------------------------------------------------ | :------------ |
| Schema Workflow Script          | `scripts/generate_schema.py`        | Orchestrates the entire schema setup process from sampling to data loading trigger.                             | Script        |
| CSV Sampler                     | `src/schema_generator/sampler.py`   | Reads headers and sample rows from input CSVs.                                                                | Deterministic |
| Schema Suggestion Prompt        | `src/llm/prompts.py`                | Function (`get_schema_suggestion_prompt`) creating the detailed prompt for the LLM.                             | Deterministic |
| LLM Client                      | `src/llm/client.py`                 | Function (`call_llm`) interacting with the OpenAI API.                                                        | LLM I/O       |
| Schema Suggestion Logic         | `src/schema_generator/suggest.py`   | Coordinates sampling, prompt generation, LLM call, basic validation, and relation fixing for schema suggestion. | Orchestration |
| **User Review & Edit**          | **Manual File Edit**                | **User manually edits `prisma/schema.prisma` based on the saved suggestion.**                                 | **Manual**    |
| Prisma CLI Executor             | `scripts/generate_schema.py`        | Executes `prisma generate` and `prisma db push` via `subprocess`.                                             | Logic / I/O   |
| Prisma CLI                      | (External Tool)                     | Command-line interface used for `generate` and `db push`.                                                     | External Tool |
| Data Loader                     | `src/data_handling/loader.py`       | Loads full CSV data into SQLite tables using pandas & SQLAlchemy `to_sql`.                                    | Deterministic |
| Dataset Analyzer (Optional)     | `src/data_handling/dataset_analysis.py` | Performs detailed statistical analysis and LLM description generation on loaded data.                         | Deterministic + LLM I/O |
| SQLite Database                 | `analysis.db`                       | The target database file (location defined by `DATABASE_URL`).                                                | Storage       |
| Prisma Schema File              | `prisma/schema.prisma`              | **Single source of truth** for DB structure, confirmed/edited by the user.                                    | Configuration |
| Environment Variables           | `.env` / `.env.local`               | Stores `DATABASE_URL` and `OPENAI_API_KEY`.                                                                 | Configuration |

## 4. `prisma/schema.prisma` File

*   **Location:** `prisma/schema.prisma`
*   **Source:** Initially suggested by LLM, **final version confirmed/edited by User**. This user-confirmed version is the single source of truth.
*   **Content:** Defines `datasource db` (provider="sqlite", url=env("DATABASE_URL")), `generator client` (provider="prisma-client-py"), and `model` blocks for each table. Includes fields with types, attributes (`@id`, `@default`, `@map`, `@relation`, `?` for optional), and model mappings (`@@map`).
*   **Syntax:** Adheres to Prisma schema language specifications. See [Prisma Schema Reference](https://www.prisma.io/docs/orm/prisma-schema/overview).
*   **Example Snippet:**
    ```prisma
    datasource db {
      provider = "sqlite"
      url      = env("DATABASE_URL") // e.g., "sqlite:../analysis.db"
    }

    generator client {
      provider = "prisma-client-py"
      // interface = "asyncio" // Optional: uncomment if needed
    }

    model Sales {
      saleId      Int       @id @default(autoincrement()) @map("sale_id") // Prisma field name vs DB column name
      customerId  Int       @map("customer_id")
      productId   Int       @map("product_id")
      amount      Float?
      saleDate    DateTime? @map("sale_date") // Use String? if formats vary wildly

      // Example Relations (Define BOTH sides)
      product     Product   @relation(fields: [productId], references: [productId])
      customer    Customer  @relation(fields: [customerId], references: [customerId])

      @@map("sales") // Maps model to DB table name 'sales'
    }

    model Product {
      productId   Int     @id @map("product_id")
      name        String
      category    String?
      price       Float?

      sales       Sales[] // Back-relation to Sales

      @@map("products")
    }

    model Customer {
      customerId  Int     @id @map("customer_id")
      firstName   String? @map("first_name")
      lastName    String? @map("last_name")
      email       String  @unique

      sales       Sales[] // Back-relation to Sales

      @@map("customers")
    }
    ```

## 5. LLM Schema Suggestion Details (`src/schema_generator/suggest.py`)

*   **Input:** Dictionary mapping CSV filenames to strings containing headers and N sample rows.
*   **Prompt (`get_schema_suggestion_prompt`):** Instructs the LLM to infer models (PascalCase), fields (camelCase/snake_case), relations (bidirectional), types (conservative: `String`, `Int`, `Float`, `Boolean`, `DateTime?`), IDs (`@id`), optionality (`?`), and mappings (`@map`, `@@map`). Emphasizes outputting *only* schema content.
*   **Output:** A single string containing the suggested `schema.prisma` file content.
*   **Validation/Fixing:**
    *   `_extract_prisma_schema_from_llm`: Removes markdown fences or preamble.
    *   `_validate_prisma_schema_output`: Performs basic structural checks and warns about potential issues (e.g., non-nullable risky types, missing relations).
    *   `_fix_missing_relations`: Attempts to automatically add missing back-relations (primarily the `Model[]` side).

## 6. User Review & Confirmation Details (Manual)

*   The `scripts/generate_schema.py` script saves the suggestion and **stops**, requiring manual user intervention.
*   The user **must** open `prisma/schema.prisma` (after copying/editing from the suggestion).
*   The user **must** verify/correct:
    *   Table names (`@@map`)
    *   Column names (`@map`) and Prisma field names
    *   Data types (`Int`, `Float`, `String`, `DateTime`, `Boolean`)
    *   Nullability (`?`)
    *   Primary Keys (`@id`, `@default(autoincrement())`)
    *   Unique constraints (`@unique`)
    *   Relationships (`@relation` on *both* sides)
*   After saving the final `prisma/schema.prisma`, the user resumes the script.

## 7. Database Setup Details (`scripts/generate_schema.py`)

*   Triggered after user resumes the script.
*   `subprocess.run(["prisma", "generate"], ...)` is executed. Checks return code.
*   `subprocess.run(["prisma", "db", "push", "--accept-data-loss"], ...)` is executed. Checks return code. Errors are reported. (`--accept-data-loss` is suitable for initial setup; `migrate dev` might be used for subsequent changes).

## 8. Data Loading Details (`src/data_handling/loader.py`)

*   Triggered by `scripts/generate_schema.py` after successful DB setup.
*   Uses pandas `read_csv` and SQLAlchemy `to_sql` (connecting via `db_uri`).
*   Basic preprocessing converts pandas `NaN`/`NaT` to `None`.
*   Potential errors if CSV data doesn't match the confirmed schema types/constraints are caught and logged.

## 9. Error Handling

*   **CSV Sampling:** Handles `FileNotFoundError`, empty files, parsing errors.
*   **LLM Call:** Handles API errors, rate limits, timeouts via `try...except` in `llm/client.py`. Suggestion logic handles invalid LLM output.
*   **User Confirmation:** Relies on the user correctly editing the schema file.
*   **Prisma CLI:** `scripts/generate_schema.py` captures `stderr` and checks return codes, reporting failures.
*   **Data Loading:** Catches SQLAlchemy errors (often type/constraint violations) and other exceptions during loading.

## 10. Assumptions & Limitations

*   Relies on the quality of the LLM's schema inference.
*   **User review is essential and assumes user understanding.**
*   The automated relation fixing (`_fix_missing_relations`) is basic. Complex relations likely require manual definition.
*   `prisma db push --accept-data-loss` will drop and recreate tables, losing existing data. Use `prisma migrate dev` for iterative changes on persistent data.
*   Data loading uses SQLAlchemy `to_sql`, which might not be the most performant method for very large datasets compared to bulk loading options if available for the target DB (though less relevant for SQLite).
