```
+-----------------+      +---------------------------------+      +---------------------------------+
|   User Input    |----->|      FastAPI Endpoint           |----->|      Workflow Orchestrator      |
| (via /analyze)  |      |      (src/api/routers/...)      |<-----|      (src/orchestration/...)    |
+-----------------+      +------------------^--------------+      +----^----------------------^-----+
                                            |                             |                      |
                                            | (SQL/Suggestions/Desc./     | (Get Context)        | (Classify Intent)
                                            |  Result/Error to User)      |                      |
                                            |                             v                      v
                                            |      +----------------------+      +----------------------+
                                            |      | DB Context Provider  |      |   Intent Classifier  |
                                            |      | (src/prisma_utils/...) |      | (src/utils/...)      |
                                            |      +----------+-----------+      +----------+-----------+
                                            |                 | (Schema, Summaries, Analysis Data) |
                                            |                 v                              v
                                            |      +----------+-----------+      +----------+-----------+
                                            |      | Prisma Schema        |      | SQLite DB            |
                                            |      | (prisma/schema.prisma)|      | (analysis.db)        |
                                            |      +----------------------+      +----------------------+
                                            |      +----------------------+
                                            |      | Analysis Results     |
                                            |      | (analysis_results/*) |
                                            |      +----------------------+
                                            |
+-------------------------------------------+----------------------------------------------------------+
|                                       Agent Layer & Flows                                            |
+-------------------------------------------+----------------------------------------------------------+
                                            | (Route based on Intent)
                                            |
           +--------------------------------+--------------------------------+-------------------------+
           | (Descriptive)                  | (Analytical)                   | (Specific)              |
           v                                v                                v                         |
+----------+-----------+         +----------+-----------+         +----------+-----------+             |
| Data Describer       |         | Planner Agent        |<--------| Planner Agent        |             |
| (in Orchestrator)    |         | (Insights Mode)      |         | (Plan Mode)          |             |
+----------+-----------+         +----------+-----------+         +----------+-----------+             |
           |                                |                                |                         |
           | (Description)                  | (Suggestions)                  | (Initial Plan)          |
           v                                v                                v                         |
+----------+-----------+         +----------+-----------+         +----------+-----------+             |
| State Store          |<--------| State Store          |<--------| Workflow Orchestrator|             |
| (In-Memory Dict)     |         | (In-Memory Dict)     |         +----------+-----------+             |
+----------------------+         +----------------------+                    | (Plan + Context)        |
           |                                |                                v                         |
           | (Desc. + SessionID)            | (Sugg. + SessionID)            +----------+-----------+             |
           v                                v                                | Plan Validator       |             |
+----------+-----------+         +----------+-----------+         | (src/agents/...)     |             |
| FastAPI Endpoint     |         | FastAPI Endpoint     |         +----------+-----------+             |
| (Response to User)   |         | (Response to User)   |                    | (Validated Plan)        |
+----------------------+         +----------------------+                    v                         |
                                                                   +----------+-----------+             |
                                                                   | Workflow Orchestrator|             |
                                                                   +----------+-----------+             |
                                                                              | (If Feasible)           |
                                                                              v                         |
                                                                   +----------+-----------+             |
                                                                   | SQL Generator Agent  |             |
                                                                   | (src/agents/...)     |             |
                                                                   +----------+-----------+             |
                                                                              | (Generated SQL)         |
                                                                              v                         |
                                                                   +----------+-----------+             |
                                                                   | Workflow Orchestrator|             |
                                                                   +----------+-----------+             |
                                                                              |                         |
                                                                              | (Store State)           |
                                                                              v                         |
                                                                   +----------+-----------+             |
                                                                   | State Store          |             |
                                                                   | (In-Memory Dict)     |             |
                                                                   +----------------------+             |
                                                                              | (SQL + SessionID)       |
                                                                              v                         |
                                                                   +----------+-----------+             |
                                                                   | FastAPI Endpoint     |------------>+ User
                                                                   | (SQL for Review)     |             | (Review/Edit SQL)
                                                                   +----------+-----------+             |
                                                                              |                         |
                                                                              | (Approved SQL + SessionID)|
                                                                              v                         |
                                                                   +----------+-----------+             |
                                                                   | FastAPI Endpoint     |<------------+
                                                                   | (/execute)           |
                                                                   +----------+-----------+
                                                                              | (Execute Request)
                                                                              v
                                                                   +----------+-----------+
                                                                   | Workflow Orchestrator|
                                                                   | (Execute Phase)      |
                                                                   +----------+-----------+
                                                                              | (Retrieve State)
                                                                              v
                                                                   +----------+-----------+
                                                                   | State Store          |
                                                                   +----------------------+
                                                                              | (Approved SQL)
                                                                              v
                                                                   +----------+-----------+
                                                                   | SQL Executor         |----------->+ SQLite DB
                                                                   | (src/prisma_utils/...) |<-----------+ (Results/Error)
                                                                   +----------+-----------+
                                                                              | (Results/Error)
                                                                              v
                                                                   +----------+-----------+
                                                                   | Workflow Orchestrator|
                                                                   +----^-----------+----^--+
                                                                        | (If Error)    | (If Success)
                                                                        v               v
                                                              +-----------+---+ +---------+----------+
                                                              | SQL Debugger  | | Interpreter Agent|
                                                              | (src/agents/..)| | (src/agents/...) |
                                                              +-----------+---+ +---------+----------+
                                                                        | (Debug Suggestion) | (Interpretation)
                                                                        v               v
                                                              +-----------+---------------+----------+
                                                              |         Workflow Orchestrator        |
                                                              +-----------------+--------------------+
                                                                                | (Final Result/Error)
                                                                                v
                                                                     +----------+-----------+
                                                                     | FastAPI Endpoint     |---------> User
                                                                     | (Response to User)   |
                                                                     +----------------------+

```

**Agent Responsibilities & Interactions (Current Implementation):**

1.  **User Input:** The user interacts via an API endpoint (e.g., `/api/analyze`), providing a natural language query.
2.  **API Endpoint (FastAPI):** Receives the request and passes it to the `Workflow Orchestrator`. Handles returning responses (SQL, suggestions, descriptions, results, errors) to the user.
3.  **Workflow Orchestrator (`src/orchestration/workflow.py`):**
    *   The central coordinator.
    *   Retrieves database context (schema + summaries + analysis data) using `src/prisma_utils/context.py`.
    *   Calls the `Intent Classifier` to determine the request type.
    *   Based on intent, routes the request to the appropriate agent or function:
        *   **Descriptive:** Calls internal logic (`generate_data_description`) to create a summary based on the context.
        *   **Analytical:** Calls the `Planner Agent` in "insights" mode.
        *   **Specific:** Initiates the multi-step analysis flow (Planner -> Validator -> SQL Generator).
    *   Manages intermediate state using an in-memory dictionary (`WORKFLOW_STATE_STORE`).
    *   Handles the execution phase after user approval, calling the `SQL Executor` and then the `Interpreter Agent`.
    *   If SQL execution fails, calls the `SQL Debugger` to get suggestions.
4.  **Intent Classifier (`src/utils/intent_classifier.py`):**
    *   Receives the user query.
    *   Uses an LLM call (primary) or rule-based logic (fallback) to classify the intent as `specific`, `exploratory_analytical`, or `exploratory_descriptive`.
    *   Returns the classification and a confidence score.
5.  **DB Context Provider (`src/prisma_utils/context.py`):**
    *   Parses the `prisma/schema.prisma` file.
    *   Connects to the SQLite DB using SQLAlchemy (`src/data_handling/db_utils.py`) to get table summaries (row counts, nulls, distinct values, basic stats).
    *   Loads pre-computed analysis data from `analysis_results/*.json` if available (`src/prisma_utils/analysis_loader.py`).
    *   Formats all this information into a structured context string optimized for LLM consumption.
6.  **Planner Agent (`src/agents/planner.py`):**
    *   Receives the user request and the database context.
    *   **Plan Mode:** Generates a conceptual, step-by-step plan for fulfilling a *specific* request. Does *not* write SQL.
    *   **Insights Mode:** Generates 5-7 actionable analytical questions or insights based on an *exploratory* request and the database context.
7.  **Plan Validator Agent (`src/agents/plan_validator.py`):**
    *   Receives the user request, the initial plan (from Planner), and the database context.
    *   Critically assesses the plan's feasibility against the available schema and data summaries.
    *   Checks for non-existent tables/columns, logical flaws, or impossible operations.
    *   Returns the final plan (original or revised), a feasibility status (FEASIBLE, NEEDS REVISION, INFEASIBLE), and an explanation if not feasible.
8.  **SQL Generator Agent (`src/agents/sql_generator.py`):**
    *   Receives the *validated* conceptual plan and the database context.
    *   Translates the plan into a single, executable SQLite SQL query.
    *   Includes internal validation logic (`_validate_sql_query`) to check table/column references and basic syntax against the context *before* returning the SQL.
    *   Attempts automatic refinement (`refine_sql_query`) using an LLM call if initial validation fails.
9.  **SQL Executor (`src/prisma_utils/executor.py`):**
    *   Receives the user-approved SQL query string.
    *   Uses the `prisma-client-py` library (async primarily, with sync wrapper and SQLite CLI fallback) to execute the raw SQL against the database.
    *   Returns the results (as a list of dictionaries) or an error message.
10. **SQL Debugger (`src/agents/sql_generator.py` - `debug_sql_error` function):**
    *   Activated only if the `SQL Executor` returns an error.
    *   Receives the original request, the failed SQL, the database error message, the plan, and the context.
    *   Uses an LLM call to analyze the error and suggest a corrected SQL query.
11. **Interpreter Agent (`src/agents/interpreter.py`):**
    *   Receives the original user request and the *successful* results from the `SQL Executor`.
    *   Generates a concise, natural-language summary of the findings, tailored to the user's original question.
12. **State Store (`WORKFLOW_STATE_STORE` in `workflow.py`):**
    *   A simple Python dictionary holding intermediate data (request, plan, generated SQL) keyed by a session ID.
    *   **Limitation:** This is in-memory and volatile; state is lost on application restart. Needs replacement with a persistent store (e.g., Redis, database table) for production use.
