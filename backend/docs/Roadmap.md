Okay, understood. Here is a technical implementation roadmap designed for an LLM, focusing on component definitions, function signatures, data structures, library usage, and control flow for the DataWeave AI architecture using FastAPI, SQLAlchemy, and SQLite.

**Objective:** Implement a multi-agent system for conversational data analysis where user requests are translated into SQL queries executed against a SQLite database, with user review of SQL via a FastAPI interface, and full history tracking.

**Phase 0: Environment Setup & Core Dependencies**

1.  **Initialize Project:**
    * Create root directory.
    * Initialize Git: `git init`.
    * Create Python virtual environment: `python -m venv venv && source venv/bin/activate` (or platform equivalent).
2.  **Install Dependencies:** Create `requirements.txt` and install:
    ```
    # Core
    python-dotenv
    pandas
    sqlalchemy

    # LLM Interaction (Choose ONE primary method)
    requests # or httpx
    # or google-generativeai / openai / anthropic SDK

    # API Layer
    fastapi
    uvicorn[standard] # ASGI server
    pydantic # For API models (often installed with fastapi)

    # Optional but Recommended
    sqlparse # For basic SQL validation/analysis
    # pandera # If deeper DataFrame validation is needed post-query
    ```
    Run `pip install -r requirements.txt`.
3.  **Configuration:**
    * Create `.env` file for secrets (e.g., `LLM_API_KEY`, `LLM_ENDPOINT`, `DATABASE_URI=sqlite:///analysis.db`). Add `.env` to `.gitignore`.
    * Implement `src/utils/config.py` using `dotenv.load_dotenv()` and `os.getenv()` to load configurations.
4.  **Directory Structure:** Create the file structure outlined previously (including `src/api`, `src/data_handling`, `src/llm`, `src/agents`, `src/orchestration`, `src/history`, `data/`, `tests/`, etc.). Create `__init__.py` files in necessary directories.

**Phase 1: Data Ingestion & Base DB Interaction Layer (`src/data_handling`)**

1.  **`loader.py`:**
    * Define function `load_csv_to_sqlite(csv_path: str, db_uri: str, table_name: str) -> None`.
    * Inputs: Path to CSV file, SQLAlchemy database URI, target table name.
    * Implementation: Use `pandas.read_csv`. Use `sqlalchemy.create_engine(db_uri)`. Use `pandas.DataFrame.to_sql(name=table_name, con=engine, if_exists='replace', index=False)`. Handle file/DB exceptions.
2.  **`db_utils.py`:**
    * Define function `get_sqlalchemy_engine(db_uri: str) -> sqlalchemy.engine.Engine`. Returns a SQLAlchemy engine instance.
    * Define function `execute_sql(engine: sqlalchemy.engine.Engine, sql_query: str) -> Tuple[List[Dict], Optional[str]]`.
        * Inputs: SQLAlchemy engine, SQL query string.
        * Outputs: Tuple containing (List of result rows as dictionaries, None on success) or (Empty List, Error message string on failure).
        * Implementation: Use `engine.connect()`, `connection.execute(sqlalchemy.text(sql_query))`, `result.mappings().all()`, `try...except sqlalchemy.exc.SQLAlchemyError as e`.
    * Define function `get_db_schema_string(engine: sqlalchemy.engine.Engine) -> str`.
        * Inputs: SQLAlchemy engine.
        * Outputs: String representation of the database schema (Tables, Columns, Types).
        * Implementation: Use `sqlalchemy.inspect(engine)`, `inspector.get_table_names()`, `inspector.get_columns(table_name)`. Format output clearly for LLM consumption.

**Phase 2: Core LLM Integration & Prompting (`src/llm`)**

1.  **`client.py`:**
    * Define function `call_llm(prompt: str, **kwargs) -> str`.
    * Inputs: Prompt string, variable keyword arguments for LLM parameters (e.g., `temperature`, `max_tokens`, `model`).
    * Outputs: Raw text response from LLM API.
    * Implementation: Use `requests.post` (or SDK equivalent) targeting endpoint from config. Construct request payload according to LLM API spec. Include API key from config. Handle HTTP/API errors. Parse response JSON/text.
2.  **`prompts.py`:**
    * Define functions returning formatted prompt strings:
        * `get_planning_prompt(user_request: str, db_schema: str) -> str`.
        * `get_sql_generation_prompt(conceptual_plan: str, db_schema: str) -> str`.
        * `get_interpretation_prompt(user_request: str, results: List[Dict]) -> str`.
    * Use f-strings or Jinja2 templates. Include clear instructions, roles, context (schema, request, plan, results), and desired output format.

**Phase 3: Agent Definitions & Orchestration Logic (`src/agents`, `src/orchestration`)**

1.  **`agents/*.py`:**
    * Define functions wrapping LLM calls for specific roles:
        * `planner.run_planner(user_request: str, db_schema: str) -> str`: Calls `llm.client.call_llm` with `llm.prompts.get_planning_prompt`. Parses output to get conceptual plan string.
        * `sql_generator.run_sql_generator(plan: str, db_schema: str) -> str`: Calls `llm.client.call_llm` with `llm.prompts.get_sql_generation_prompt`. Parses output to extract SQL query string (handle code blocks etc.).
        * `interpreter.run_interpreter(user_request: str, results: List[Dict]) -> str`: Calls `llm.client.call_llm` with `llm.prompts.get_interpretation_prompt`.
2.  **`orchestration/workflow.py`:**
    * Define primary orchestration function/class method: `initiate_analysis(user_request: str, db_uri: str) -> Dict[str, str]`.
        * Inputs: User query, database URI.
        * Outputs: Dictionary containing `{'session_id': str, 'generated_sql': str}`.
        * Steps:
            1. Generate `session_id = uuid.uuid4().hex`.
            2. Get `engine = db_utils.get_sqlalchemy_engine(db_uri)`.
            3. Get `db_schema = db_utils.get_db_schema_string(engine)`.
            4. Log initial request step using `history.manager.log_step`.
            5. Call `plan = agents.planner.run_planner(user_request, db_schema)`.
            6. Log planning step.
            7. Call `generated_sql = agents.sql_generator.run_sql_generator(plan, db_schema)`.
            8. Log SQL generation step (store `generated_sql` associated with `session_id`, maybe in a temporary state store or history log itself).
            9. Return `{'session_id': session_id, 'generated_sql': generated_sql}`.
    * Define secondary orchestration function/class method: `execute_approved_analysis(session_id: str, approved_sql: str, db_uri: str, original_request: str) -> Dict[str, Any]`.
        * Inputs: Session ID, user-approved SQL, DB URI, original user request (retrieved based on session_id).
        * Outputs: Dictionary containing `{'interpretation': str, 'results': List[Dict], 'history': List[Dict]}`.
        * Steps:
            1. Log SQL approval step.
            2. Get `engine = db_utils.get_sqlalchemy_engine(db_uri)`.
            3. Call `results, error = db_utils.execute_sql(engine, approved_sql)`.
            4. Log execution step (include results snippet or error).
            5. If `error`, handle/return error appropriately.
            6. Call `interpretation = agents.interpreter.run_interpreter(original_request, results)`.
            7. Log interpretation step.
            8. Retrieve full history using `history.manager.get_history(db_uri, session_id)`.
            9. Return `{'interpretation': interpretation, 'results': results, 'history': history}`.

**Phase 4: API Layer (`src/api`)**

1.  **`api/models.py`:**
    * Define Pydantic `BaseModel` classes: `AnalysisRequest`, `GeneratedSQLResponse`, `ExecuteRequest`, `AnalysisResultResponse`, `HistoryLogEntry`, `ErrorResponse`. Ensure field types match expected data.
2.  **`api/routers/analysis.py`:**
    * Create `router = fastapi.APIRouter()`.
    * Define endpoint `POST /analyze` -> `analyze_endpoint(request: models.AnalysisRequest) -> models.GeneratedSQLResponse | models.ErrorResponse`:
        * Load `db_uri` from config.
        * Call `orchestration.workflow.initiate_analysis(request.query, db_uri)`.
        * Return `GeneratedSQLResponse` or `ErrorResponse`.
    * Define endpoint `POST /execute` -> `execute_endpoint(request: models.ExecuteRequest) -> models.AnalysisResultResponse | models.ErrorResponse`:
        * Load `db_uri` from config.
        * Retrieve `original_request` associated with `request.session_id` (from history/state store).
        * Call `orchestration.workflow.execute_approved_analysis(request.session_id, request.approved_sql, db_uri, original_request)`.
        * Return `AnalysisResultResponse` or `ErrorResponse`.
    * Define endpoint `GET /history/{session_id}` -> `get_history_endpoint(session_id: str) -> List[models.HistoryLogEntry] | models.ErrorResponse`:
        * Load `db_uri` from config.
        * Call `history.manager.get_history(db_uri, session_id)`.
        * Return list of history logs or error.
3.  **`api/main.py`:**
    * `app = fastapi.FastAPI()`.
    * `app.include_router(analysis.router, prefix="/api/v1")`.
    * Add root endpoint `@app.get("/")`. Add basic error handling middleware if needed.

**Phase 5: History Management Implementation (`src/history`)**

1.  **`manager.py`:**
    * Define SQLAlchemy `HistoryLog` model (declarative base or Core Table object) matching `api.models.HistoryLogEntry` Pydantic schema. Ensure table creation (`metadata.create_all(engine)`).
    * Implement `log_step(db_uri: str, session_id: str, step_name: str, input_data: Dict, output_data: Dict, status: str) -> None`:
        * Create engine/session using `db_uri`.
        * Create `HistoryLog` instance.
        * Serialize `input_data`, `output_data` (e.g., to JSON strings) before storing if they are complex dicts/lists.
        * Add and commit the record using SQLAlchemy session. Handle DB errors.
    * Implement `get_history(db_uri: str, session_id: str) -> List[Dict]`:
        * Create engine/session.
        * Query `HistoryLog` table, filter by `session_id`, order by timestamp.
        * Deserialize JSON fields if necessary.
        * Return results as a list of dictionaries.
    * Implement logic to store/retrieve intermediate state (like `generated_sql` linked to `session_id`) needed between `/analyze` and `/execute`. This could be part of the `HistoryLog` table or a separate temporary store.

**Phase 6: User Interaction Logic (API Contract)**

* The primary implementation is the two-step API design (`/analyze` -> returns SQL/ID, `/execute` -> takes SQL/ID).
* The client (Web UI or other consumer) is responsible for displaying the SQL, enabling editing, and calling the `/execute` endpoint with the final `approved_sql`.
* Implement temporary state storage within the backend (e.g., using `history.manager` or a simple cache) to link the `generated_sql` from `/analyze` to the `session_id` for retrieval during the `/execute` call. Ensure this temporary state has appropriate cleanup/expiry.

**Phase 7: Testing & Refinement**

1.  **Unit Tests (`tests/`)**:
    * Write `pytest` tests for individual functions in `data_handling`, `llm`, `agents`, `history`.
    * Use `unittest.mock.patch` to mock LLM API calls (`llm.client.call_llm`) and potentially DB interactions.
2.  **Integration Tests (`tests/`)**:
    * Test the orchestration flow (`orchestration.workflow`).
    * Use `fastapi.testclient.TestClient` to test API endpoints (`api.routers.analysis`) end-to-end, potentially using a dedicated test database.
3.  **Refinement**:
    * Iteratively refine prompts in `llm.prompts.py` based on LLM performance during testing.
    * Enhance error handling and logging across all modules.
    * Implement SQL validation/sanitization in `validation.sql_validator.py` and integrate before execution if desired.
    * Optimize database queries and LLM calls.

This roadmap provides a structured, technical plan suitable for guiding development or explaining the implementation process to another technical entity, including an LLM.