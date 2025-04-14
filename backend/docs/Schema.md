# DataWeave AI: Prisma Schema Generation and Workflow Specification

**Version:** 1.0
**Date:** 2025-04-14

## 1. Overview

This document outlines the process for defining and establishing the database schema used by the DataWeave AI analysis engine. The system utilizes Prisma as its schema definition tool and migration manager, targeting a SQLite database (`analysis.db`).

To balance automation with accuracy, especially when dealing with user-provided CSV data of unknown structure, a **hybrid approach** is employed:

1.  An LLM **suggests** an initial `schema.prisma` based on sampling input CSV files.
2.  The **user reviews, potentially edits, and confirms** this suggested schema via the application interface.
3.  The user-confirmed schema is then used by Prisma to **set up the database structure**.
4.  Finally, data is **loaded** into the established tables.

This approach leverages the LLM's ability to quickly draft a schema while ensuring correctness through mandatory user oversight before database modifications occur.

## 2. Workflow Steps

The high-level workflow for schema setup and data loading is as follows:

1.  **User Provides Data:** User uploads or specifies the location of input CSV files.
2.  **CSV Sampling:** The system reads headers and the first N rows (e.g., 10) from each CSV file.
3.  **LLM Schema Suggestion:** The sampled data is sent to the configured LLM with a carefully crafted prompt, asking it to infer and generate a *suggested* `schema.prisma` content suitable for SQLite.
4.  **User Review & Confirmation:** The application presents the LLM-suggested schema content to the user in an editable format. The user reviews, modifies if necessary (correcting types, relations, etc.), and explicitly confirms the schema.
5.  **Save Confirmed Schema:** The final, user-approved schema content is saved to the `prisma/schema.prisma` file.
6.  **Generate Prisma Client:** The `prisma generate` command is run to update the type-safe Python client based on the confirmed schema.
7.  **Setup Database Schema:** The `prisma db push` command is executed (using `--accept-data-loss` in development/initial setup, potentially `prisma migrate dev` later) to synchronize the SQLite database structure (`analysis.db`) with the confirmed `schema.prisma`.
8.  **Load Data:** Data from the original CSV files is loaded into the corresponding tables in the now-structured SQLite database.
9.  **Analysis Ready:** The system is now ready for the main analysis workflow (Planning, SQL Generation, Execution, Interpretation) using the context derived from the user-confirmed schema.

## 3. Components Involved

| Component                       | Location (Tentative)                | Responsibility                                                                                                | Type          |
| :------------------------------ | :---------------------------------- | :------------------------------------------------------------------------------------------------------------ | :------------ |
| CSV Sampler                     | `src/schema_generator/sampler.py`   | Reads headers and sample rows from input CSVs.                                                                | Deterministic |
| Schema Suggestion Prompt        | `src/llm/prompts.py`                | Function (`get_schema_suggestion_prompt`) creating the detailed prompt for the LLM.                             | Deterministic |
| LLM Client                      | `src/llm/client.py`                 | Function (`call_llm`) interacting with the configured LLM API (e.g., OpenAI GPT-4o).                          | LLM I/O       |
| Schema Suggestion Orchestrator  | `src/schema_generator/suggest.py`   | Coordinates sampling, prompt generation, LLM call, and basic validation for schema suggestion.                  | Orchestration |
| Schema Review UI                | `app.py` (or frontend component)    | Displays suggested schema, provides text area for editing, captures user confirmation via button click.       | UI / Logic    |
| Schema Saver & DB Setup Trigger | `app.py` (or backend API handler) | Saves confirmed schema to file, executes `prisma generate` and `prisma db push` via `subprocess`.             | Logic / I/O   |
| Prisma CLI                      | (External Tool)                     | Command-line interface used for `generate` and `db push`/`migrate dev`.                                       | External Tool |
| Data Loader                     | `src/data_handling/loader.py`       | Loads full CSV data into SQLite tables defined by Prisma, using SQLAlchemy `to_sql` or Prisma Client `create_many`. | Deterministic |
| SQLite Database                 | `analysis.db`                       | The target database file.                                                                                     | Storage       |
| `.env` / Config                 | `.env` / `src/utils/config.py`      | Stores `DATABASE_URL` and LLM API keys.                                                                     | Configuration |

## 4. `schema.prisma` File

* **Location:** `prisma/schema.prisma`
* **Source:** Generated by LLM, **confirmed/edited by User**. This user-confirmed version is the single source of truth for the database structure.
* **Content:** Defines `datasource db` (provider="sqlite", url=env("DATABASE_URL")), `generator client` (provider="prisma-client-py"), and `model` blocks for each table inferred/confirmed.
* **Syntax:** Adheres to Prisma schema language specifications. See [Prisma Schema Reference](https://www.prisma.io/docs/orm/prisma-schema/overview).
* **Example Snippet:**
    ```prisma
    datasource db {
      provider = "sqlite"
      url      = env("DATABASE_URL")
    }

    generator client {
      provider = "prisma-client-py"
    }

    model Sales {
      sale_id     Int       @id @default(autoincrement())
      customer_id Int
      product_id  Int
      amount      Float?
      sale_date   DateTime? // Or String if formats vary wildly

      // Example Relation (if Product model exists)
      // product     Product  @relation(fields: [product_id], references: [product_id])
      // customer    Customer @relation(fields: [customer_id], references: [customer_id])

      @@map("sales")
    }

    // Other models like Product, Customer...
    ```

## 5. LLM Schema Suggestion Details

* **Input:** Dictionary mapping CSV filenames to strings containing headers and N sample rows. (`src/schema_generator/sampler.py`)
* **Prompt (`get_schema_suggestion_prompt`):** Must instruct the LLM to:
    * Infer models, fields, relations.
    * Use SQLite-compatible Prisma types (`String`, `Int`, `Float`, `Boolean`, `DateTime`). Be conservative with types (default to `String` if uncertain).
    * Identify potential `@id` and optional `?` fields.
    * Output *only* valid `schema.prisma` content.
    * Explicitly state it's a suggestion for user review.
* **Output:** A single string containing the suggested `schema.prisma` file content.
* **Validation:** Basic checks (`datasource`, `generator`, `model` keywords exist) are performed in `src/schema_generator/suggest.py`. More robust validation (e.g., `prisma validate` via subprocess) could be added.

## 6. User Review & Confirmation Details

* The application UI **must** present the full suggested schema content clearly.
* An editable text area **must** be provided for user modifications.
* A confirmation action (e.g., "Confirm Schema & Setup Database" button) **must** be present.
* **User Responsibility:** The user is responsible for verifying the correctness of table/column names, data types (especially `Int` vs `Float`, `DateTime` vs `String`), nullability (`?`), IDs (`@id`), and relationships (`@relation`) before confirming.
* **Optional:** Running `prisma format` on the user-edited content before saving can help catch syntax errors.

## 7. Database Setup Details

* Triggered after user confirmation.
* The confirmed schema text overwrites `prisma/schema.prisma`.
* `subprocess.run(["prisma", "generate"], ...)` is executed. Check return code and output.
* `subprocess.run(["prisma", "db", "push", "--accept-data-loss"], ...)` (or `migrate dev`) is executed. Check return code and output/error. Errors must be surfaced to the user.

## 8. Data Loading Details

* Triggered after successful database setup.
* Uses `src/data_handling/loader.py`.
* Must handle potential errors if data in the CSV doesn't conform to the data type defined in the user-confirmed `schema.prisma` (e.g., loading "abc" into an `Int` column).

## 9. Error Handling

* **CSV Sampling:** Handle `FileNotFoundError`, permission errors, empty files, parsing errors.
* **LLM Call:** Handle API errors, rate limits, timeouts, empty/invalid responses using `try...except` in `llm/client.py` and `schema_generator/suggest.py`.
* **Schema Validation:** Handle cases where LLM output fails basic structural checks.
* **User Confirmation:** UI should handle potential errors during file save or subprocess execution.
* **Prisma CLI:** Capture `stderr` and check return codes from `prisma generate` and `prisma db push`. Report errors clearly to the user.
* **Data Loading:** Catch exceptions during DataFrame processing or database insertion (e.g., type mismatches, constraint violations).

## 10. Assumptions & Limitations

* Relies on the quality of the LLM's schema inference capabilities.
* **User review is essential** and assumes the user has sufficient understanding to validate/correct the schema.
* The basic LLM output validation is not exhaustive; `prisma db push` is the ultimate validation of schema correctness for the database.
* Currently targets SQLite; extending to other databases would require changes in the `datasource` block and potentially type mappings.
* Relationship inference by the LLM may be basic and require significant user correction.
* Error handling during the setup phase needs to be robust to guide the user.