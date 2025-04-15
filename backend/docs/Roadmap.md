This roadmap outlines the technical implementation phases based on the current state of the DataWeave AI backend, utilizing FastAPI, Prisma, OpenAI, and SQLite.

**Objective:** Implement a multi-agent system for conversational data analysis where user requests are classified, translated into validated SQL queries executed against a Prisma-managed SQLite database, with user review of SQL via a FastAPI interface, and optional dataset analysis capabilities.

**Core Technologies:**

*   **Backend Framework:** FastAPI (Async)
*   **Database ORM & Schema:** Prisma Client Python
*   **Database:** SQLite (`analysis.db`)
*   **LLM:** OpenAI (via `openai` library)
*   **Data Handling:** Pandas, SQLAlchemy (for summaries)
*   **API Server:** Uvicorn

**Phase 0: Environment Setup & Core Dependencies (Implemented)**

1.  **Project Initialization:** Standard Python project setup with Git, virtual environment.
2.  **Dependencies:** `requirements.txt` includes `fastapi`, `uvicorn`, `openai`, `prisma`, `pandas`, `sqlalchemy`, `python-dotenv`.
3.  **Configuration:** `.env` / `.env.local` for `OPENAI_API_KEY` and `DATABASE_URL`. Loaded via `dotenv` in `llm/client.py` and used by Prisma.
4.  **Directory Structure:** Established structure with `src/`, `scripts/`, `prisma/`, `data/`, `tests/`, `docs/`.

**Phase 1: Schema Generation & Database Setup (Implemented)**

1.  **CSV Sampling (`src/schema_generator/sampler.py`):** Reads headers and sample rows from input CSVs.
2.  **LLM Schema Suggestion (`src/schema_generator/suggest.py`, `src/llm/prompts.py`):**
    *   Uses sampled data to prompt LLM (`get_schema_suggestion_prompt`) for a `schema.prisma` suggestion.
    *   Includes basic validation and attempts to fix missing bidirectional relations.
3.  **User Review & Confirmation (Manual/Scripted):**
    *   The suggested schema is intended for user review (currently via `scripts/generate_schema.py` which saves the suggestion).
    *   User manually edits/confirms `prisma/schema.prisma`. **Crucial Step.**
4.  **Prisma Client Generation (`scripts/generate_schema.py`):** Runs `prisma generate`.
5.  **Database Schema Push (`scripts/generate_schema.py`):** Runs `prisma db push --accept-data-loss` to create/update the SQLite DB schema based on `prisma/schema.prisma`.

**Phase 2: Data Loading & Initial Analysis (Implemented)**

1.  **Data Loading (`src/data_handling/loader.py`):**
    *   Uses `pandas.read_csv` and `DataFrame.to_sql` (via SQLAlchemy engine) to load data from CSVs into the tables created by Prisma.
    *   Handles multiple CSVs via `load_multiple_csvs_to_sqlite`.
2.  **Dataset Analysis (Optional) (`src/data_handling/dataset_analysis.py`):**
    *   Performs detailed statistical analysis on DataFrames (loaded from CSVs).
    *   Uses LLM (`get_column_descriptions`) to infer column meanings.
    *   Saves results to JSON files in `analysis_results/`.
    *   Can be triggered via `prompt_and_analyze_datasets`.

**Phase 3: Core LLM Integration & Context Provisioning (Implemented)**

1.  **LLM Client (`src/llm/client.py`):**
    *   Provides `call_llm` function wrapping OpenAI API calls (`gpt-4o`).
    *   Handles API key loading, basic retry logic, and in-memory conversation history management.
2.  **Prompt Engineering (`src/llm/prompts.py`):**
    *   Contains specialized prompt generation functions for each agent task (planning, SQL generation, interpretation, validation, debugging, schema suggestion, insights, classification).
3.  **Database Context Provider (`src/prisma_utils/context.py`):**
    *   Parses `prisma/schema.prisma` to understand model structure, fields, and relations.
    *   Uses SQLAlchemy (`src/data_handling/db_utils.py`) to fetch live data summaries (counts, nulls, stats) from the DB.
    *   Loads and incorporates pre-computed analysis results from `analysis_results/` if available (`src/prisma_utils/analysis_loader.py`).
    *   Formats this combined information into a rich context string for LLM agents.

**Phase 4: Agent Definitions & Orchestration Logic (Implemented)**

1.  **Intent Classification (`src/utils/intent_classifier.py`):** Classifies user request as `specific`, `exploratory_analytical`, or `exploratory_descriptive` using LLM/rules.
2.  **Agent Implementations (`src/agents/*.py`):**
    *   `planner.run_planner`: Generates plans or insights based on mode.
    *   `plan_validator.run_plan_validator`: Assesses and refines plans for feasibility.
    *   `sql_generator.run_sql_generator`: Generates SQL, includes internal validation and refinement loop.
    *   `sql_generator.debug_sql_error`: Suggests fixes for failed SQL queries.
    *   `interpreter.run_interpreter`: Summarizes results in natural language.
3.  **Workflow Orchestration (`src/orchestration/workflow.py`):**
    *   Defines `initiate_analysis_async` and `execute_approved_analysis_async`.
    *   Handles the overall flow based on classified intent.
    *   Manages the multi-step process for specific requests (Plan -> Validate -> Generate SQL).
    *   Handles the execution flow (Execute -> Interpret/Debug).
    *   Uses an in-memory dictionary (`WORKFLOW_STATE_STORE`) for session state. **Limitation:** Volatile state.

**Phase 5: API Layer & Execution (Implemented)**

1.  **API Models (`src/api/models.py`):** Pydantic models define request/response structures for type safety and validation. Includes different response types based on analysis outcome (SQL, suggestions, description, results, error).
2.  **API Routers (`src/api/routers/analysis.py`):**
    *   Defines async FastAPI endpoints (`/analyze`, `/execute`).
    *   `/analyze`: Takes user query, calls `initiate_analysis_async`, returns appropriate response based on intent (SQL, suggestions, description, or error).
    *   `/execute`: Takes session ID and approved SQL, calls `execute_approved_analysis_async`, returns results/interpretation or error (with potential debug suggestion).
3.  **API Main (`src/api/main.py`):** Initializes FastAPI app, includes router, CORS middleware, health check.
4.  **SQL Execution (`src/prisma_utils/executor.py`):**
    *   Provides `execute_prisma_raw_sql_async` using `prisma-client-py`.
    *   Includes `execute_prisma_raw_sql_sync` wrapper.
    *   Provides `execute_sqlite_cli_sql` as a fallback mechanism.

**Phase 6: User Interaction Logic (API Contract - Implemented)**

*   The backend exposes a two-step API for specific analyses:
    1.  `POST /analyze`: Returns `GeneratedSQLResponse` (with `session_id` and `generated_sql`) or other response types for exploratory requests.
    2.  `POST /execute`: Client sends `session_id` and `approved_sql` (potentially edited). Backend retrieves state, executes, interprets, and returns `AnalysisResultResponse` or `ErrorResponse`.
*   Client (e.g., Web UI - not included) is responsible for the SQL review/edit step between `/analyze` and `/execute`.
*   Intermediate state (`generated_sql`, `plan`, etc.) is currently held in the volatile `WORKFLOW_STATE_STORE`.

**Phase 7: Testing & Refinement (Partially Implemented)**

1.  **Unit Tests (`tests/`):** Some tests exist (e.g., `test_db_utils.py`). More comprehensive unit tests for agents, utils, and orchestration are needed. Mocking LLM calls is essential.
2.  **Integration Tests:** `scripts/test_workflow.py` provides basic end-to-end testing. API testing using `fastapi.testclient.TestClient` is recommended.
3.  **Refinement:** Ongoing process of improving prompts, error handling, logging, and potentially adding more robust pre-execution SQL validation.

**Future Enhancements / Next Steps:**

1.  **Persistent State/History:** Replace `WORKFLOW_STATE_STORE` with a persistent solution (e.g., Redis cache, dedicated history table in the DB managed by Prisma).
2.  **Web Frontend:** Develop a user interface to interact with the API, display results, and facilitate the SQL review/edit step.
3.  **Enhanced SQL Validation:** Implement more robust pre-execution SQL validation (e.g., using `sqlglot` or similar libraries) beyond the current reference checks.
4.  **Streaming Responses:** For long-running LLM calls or interpretations, implement streaming API responses.
5.  **Security:** Add authentication/authorization to API endpoints. Sanitize inputs more rigorously.
6.  **Observability:** Integrate more detailed logging, tracing, and monitoring.
7.  **Deployment:** Containerize the application (Dockerfile) and set up deployment pipelines (e.g., Docker Compose, Kubernetes).
