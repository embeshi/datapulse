```mermaid
graph LR
    subgraph "User Interaction"
        User(User Input)
    end

    subgraph "Core Orchestration & API"
        API(FastAPI Endpoint<br>/api/analyze)
        Orchestrator(Workflow Orchestrator<br>src/orchestration/workflow.py)
        IntentClassifier(Intent Classifier<br>src/utils/intent_classifier.py)
        Context(DB Context Provider<br>src/prisma_utils/context.py)
        State(State Store<br>[In-Memory Dict])
    end

    subgraph "Agent Layer"
        Planner(Planner Agent<br>src/agents/planner.py)
        Validator(Plan Validator<br>src/agents/plan_validator.py)
        SQLGenerator(SQL Generator<br>src/agents/sql_generator.py)
        Interpreter(Interpreter Agent<br>src/agents/interpreter.py)
        SQLDebugger(SQL Debugger<br>src/agents/sql_generator.py)
        Describer(Data Describer<br>src/orchestration/workflow.py)
    end

    subgraph "Data & Execution Layer"
        Executor(SQL Executor<br>src/prisma_utils/executor.py)
        DB[(SQLite DB<br>analysis.db)]
        Schema(Prisma Schema<br>prisma/schema.prisma)
        AnalysisData(Analysis Results<br>analysis_results/*.json)
    end

    User -- Request --> API
    API -- User Query --> Orchestrator
    Orchestrator -- Get Context --> Context
    Context -- Schema Info --> Schema
    Context -- Analysis Info --> AnalysisData
    Context -- Data Summaries --> DB
    Context -- Formatted Context --> Orchestrator

    Orchestrator -- Classify Intent --> IntentClassifier
    IntentClassifier -- Intent --> Orchestrator

    Orchestrator -- Route based on Intent --> Describer
    Orchestrator -- Route based on Intent --> Planner
    Orchestrator -- Route based on Intent --> Planner

    subgraph "Specific Analysis Flow"
        Orchestrator -- Request + Context --> Planner(Plan Mode)
        Planner -- Initial Plan --> Orchestrator
        Orchestrator -- Plan + Context --> Validator
        Validator -- Validated/Refined Plan + Feasibility --> Orchestrator
        Orchestrator -- If Feasible --> SQLGenerator
        SQLGenerator -- Generated SQL --> Orchestrator
        Orchestrator -- Store State --> State
        Orchestrator -- Generated SQL + SessionID --> API
        API -- SQL for Review --> User
        User -- Approved/Edited SQL + SessionID --> API(Execute Endpoint)
        API(Execute Endpoint) -- Approved SQL + SessionID --> Orchestrator(Execute)
        Orchestrator(Execute) -- Retrieve State --> State
        Orchestrator(Execute) -- Approved SQL --> Executor
        Executor -- Execute --> DB
        Executor -- Results/Error --> Orchestrator(Execute)
        Orchestrator(Execute) -- If Error --> SQLDebugger
        SQLDebugger -- Debug Suggestion --> Orchestrator(Execute)
        Orchestrator(Execute) -- Debug Suggestion --> API(Execute Endpoint) --> User
        Orchestrator(Execute) -- If Success --> Interpreter
        Interpreter -- Interpretation --> Orchestrator(Execute)
        Orchestrator(Execute) -- Final Result --> API(Execute Endpoint) --> User
    end

    subgraph "Exploratory Analytical Flow"
        Orchestrator -- Request + Context --> Planner(Insights Mode)
        Planner -- Suggestions --> Orchestrator
        Orchestrator -- Store State --> State
        Orchestrator -- Suggestions + SessionID --> API
        API -- Suggestions --> User
    end

    subgraph "Exploratory Descriptive Flow"
        Orchestrator -- Request + Context --> Describer
        Describer -- Description --> Orchestrator
        Orchestrator -- Store State --> State
        Orchestrator -- Description + SessionID --> API
        API -- Description --> User
    end
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
