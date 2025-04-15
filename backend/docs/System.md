```mermaid
graph TD
    subgraph External
        User(User)
        CSV(CSV Files)
    end

    subgraph Setup Phase (Scripts)
        SchemaScript(scripts/generate_schema.py)
        Sampler(src/schema_generator/sampler.py)
        SchemaSuggest(src/schema_generator/suggest.py)
        LLMClientSetup(src/llm/client.py)
        PrismaCLI(Prisma CLI)
        DataLoader(src/data_handling/loader.py)
        DatasetAnalyzer(src/data_handling/dataset_analysis.py)
    end

    subgraph Runtime Phase (FastAPI Application)
        API(FastAPI App<br>src/api/main.py)
        Router(Analysis Router<br>src/api/routers/analysis.py)
        Orchestrator(Workflow Orchestrator<br>src/orchestration/workflow.py)
        IntentClassifier(Intent Classifier<br>src/utils/intent_classifier.py)
        ContextProvider(DB Context Provider<br>src/prisma_utils/context.py)
        Planner(Planner Agent<br>src/agents/planner.py)
        Validator(Plan Validator<br>src/agents/plan_validator.py)
        SQLGenerator(SQL Generator Agent<br>src/agents/sql_generator.py)
        SQLExecutor(SQL Executor<br>src/prisma_utils/executor.py)
        SQLDebugger(SQL Debugger<br>src/agents/sql_generator.py)
        Interpreter(Interpreter Agent<br>src/agents/interpreter.py)
        LLMClientRuntime(src/llm/client.py)
        StateStore([In-Memory State<br>workflow.py])
    end

    subgraph Data Persistence & Config
        DB[(SQLite DB<br>analysis.db)]
        Schema(Prisma Schema<br>prisma/schema.prisma)
        AnalysisResults(Analysis Results<br>analysis_results/*.json)
        EnvVars(Environment Vars<br>.env / .env.local)
    end

    %% Setup Flow
    CSV --> Sampler
    Sampler -- Samples --> SchemaSuggest
    SchemaSuggest -- Prompt --> LLMClientSetup
    LLMClientSetup -- API Key --> EnvVars
    LLMClientSetup -- Suggestion --> SchemaSuggest
    SchemaSuggest -- Suggested Schema --> SchemaScript
    SchemaScript -- "User Review/Edit" --> Schema
    Schema -- User Confirmed --> SchemaScript
    SchemaScript -- Run Generate --> PrismaCLI
    SchemaScript -- Run DB Push --> PrismaCLI
    PrismaCLI -- Modifies --> DB
    SchemaScript -- Trigger Load --> DataLoader
    DataLoader -- Reads --> CSV
    DataLoader -- Writes --> DB
    SchemaScript -- Trigger Analysis? --> DatasetAnalyzer
    DatasetAnalyzer -- Reads --> DB
    DatasetAnalyzer -- Prompt --> LLMClientSetup
    DatasetAnalyzer -- Writes --> AnalysisResults

    %% Runtime Flow
    User -- HTTP Request --> API
    API -- Routes --> Router
    Router -- Request Data --> Orchestrator
    Orchestrator -- Get Context --> ContextProvider
    ContextProvider -- Reads --> Schema
    ContextProvider -- Reads --> DB
    ContextProvider -- Reads --> AnalysisResults
    ContextProvider -- Context String --> Orchestrator
    Orchestrator -- Query --> IntentClassifier
    IntentClassifier -- Prompt --> LLMClientRuntime
    LLMClientRuntime -- API Key --> EnvVars
    IntentClassifier -- Intent --> Orchestrator

    %% Specific Analysis Path
    Orchestrator -- Request+Context --> Planner
    Planner -- Prompt --> LLMClientRuntime
    Planner -- Initial Plan --> Orchestrator
    Orchestrator -- Plan+Context --> Validator
    Validator -- Prompt --> LLMClientRuntime
    Validator -- Validated Plan --> Orchestrator
    Orchestrator -- Plan+Context --> SQLGenerator
    SQLGenerator -- Prompt --> LLMClientRuntime
    SQLGenerator -- Generated SQL --> Orchestrator
    Orchestrator -- Store --> StateStore
    Orchestrator -- SQL+SessionID --> Router
    Router -- HTTP Response --> User
    User -- Approved SQL+SessionID --> API
    Router -- Execute Request --> Orchestrator
    Orchestrator -- Retrieve --> StateStore
    Orchestrator -- SQL --> SQLExecutor
    SQLExecutor -- Query --> DB
    SQLExecutor -- Results/Error --> Orchestrator
    Orchestrator -- If Error --> SQLDebugger
    SQLDebugger -- Prompt --> LLMClientRuntime
    SQLDebugger -- Suggestion --> Orchestrator
    Orchestrator -- If Success --> Interpreter
    Interpreter -- Prompt --> LLMClientRuntime
    Interpreter -- Interpretation --> Orchestrator
    Orchestrator -- Final Result/Error --> Router
    Router -- HTTP Response --> User

    %% Exploratory Paths (Simplified)
    Orchestrator -- Request+Context (Insights) --> Planner
    Planner -- Insights --> Orchestrator --> Router --> User
    Orchestrator -- Request+Context (Describe) --> Orchestrator -- Description --> Router --> User

    %% Style
    classDef script fill:#f9f,stroke:#333,stroke-width:2px;
    classDef api fill:#ccf,stroke:#333,stroke-width:2px;
    classDef agent fill:#ff9,stroke:#333,stroke-width:2px;
    classDef data fill:#9cf,stroke:#333,stroke-width:2px;
    classDef manual fill:#fcc,stroke:#333,stroke-width:2px;

    class SchemaScript,Sampler,SchemaSuggest,DataLoader,DatasetAnalyzer script;
    class API,Router,Orchestrator,IntentClassifier,ContextProvider,SQLExecutor,StateStore api;
    class Planner,Validator,SQLGenerator,SQLDebugger,Interpreter,LLMClientSetup,LLMClientRuntime agent;
    class DB,Schema,AnalysisResults,EnvVars,CSV data;
    class User manual;
```

**System Overview:**

The system is divided into two main phases: Setup and Runtime.

**Setup Phase (Orchestrated by `scripts/generate_schema.py`):**

1.  **Data Input:** Starts with user-provided CSV files.
2.  **Schema Suggestion:** Samples CSVs (`Sampler`), uses an LLM (`SchemaSuggest`, `LLMClientSetup`) to generate a draft `schema.prisma`. Includes basic validation and relation fixing.
3.  **User Confirmation (Manual):** The script pauses, requiring the user to manually review, edit, and save the final schema into `prisma/schema.prisma`. This step is critical for ensuring schema correctness.
4.  **Database Setup:** The script resumes, using the `Prisma CLI` to generate the client and push the confirmed schema to the SQLite `DB`.
5.  **Data Loading:** The `DataLoader` loads data from the CSVs into the newly structured database tables using pandas and SQLAlchemy.
6.  **(Optional) Dataset Analysis:** `DatasetAnalyzer` can be run to perform deeper statistical analysis and generate LLM-based column descriptions, saving results to `AnalysisResults`.

**Runtime Phase (FastAPI Application):**

1.  **API Interface:** The `User` interacts with the system via HTTP requests to the `FastAPI App`. The `Analysis Router` directs traffic.
2.  **Orchestration:** The `Workflow Orchestrator` is the central component.
3.  **Context Generation:** On receiving a request, the `Orchestrator` gets database context from the `ContextProvider`, which reads the `Prisma Schema`, queries the `DB` for summaries (using SQLAlchemy utils), and loads any pre-computed `AnalysisResults`.
4.  **Intent Classification:** The `Orchestrator` uses the `IntentClassifier` (backed by `LLMClientRuntime`) to determine if the request is specific, analytical, or descriptive.
5.  **Workflow Branching:**
    *   **Descriptive:** The `Orchestrator` generates a description based on the context and returns it.
    *   **Analytical:** The `Orchestrator` calls the `Planner` in "insights" mode, returning suggestions.
    *   **Specific:** A multi-step process ensues:
        *   `Planner` creates a conceptual plan.
        *   `Validator` assesses and refines the plan.
        *   `SQLGenerator` translates the valid plan into SQL, performing its own validation and refinement loop.
        *   The `Orchestrator` stores intermediate state (`StateStore` - currently in-memory) and returns the generated SQL and a session ID to the user via the API.
6.  **Execution Flow:**
    *   The `User` reviews the SQL (potentially edits it) and sends it back to the `/execute` endpoint with the session ID.
    *   The `Orchestrator` retrieves state, sends the approved SQL to the `SQLExecutor`.
    *   The `SQLExecutor` runs the query against the `DB` using Prisma Client Python.
    *   **Error Handling:** If execution fails, the `SQLDebugger` is invoked to suggest a fix, which is returned to the user.
    *   **Success:** If execution succeeds, the `Interpreter` generates a natural language summary of the results.
    *   The final interpretation and raw results (or error/debug suggestion) are returned to the user via the API.

**Key Characteristics:**

*   **Prisma-Centric:** `prisma/schema.prisma` is the source of truth for DB structure. `prisma-client-py` is used for execution.
*   **Hybrid Schema Generation:** Combines LLM suggestion with mandatory manual user review.
*   **Agent-Based:** Different LLM-powered agents handle distinct tasks (planning, validation, SQL generation, interpretation, debugging, classification).
*   **Async API:** FastAPI enables asynchronous handling of requests.
*   **Rich Context:** Context provided to LLMs includes schema, live DB summaries, and optional pre-computed analysis data.
*   **Intent-Driven:** Workflow adapts based on the classified user intent.
*   **SQL Review Loop:** Explicitly designed for user review and approval of generated SQL before execution.
*   **In-Memory State:** Current limitation - session state is lost on restart.

## Scalability Considerations

The current architecture provides a foundation for scalability, but certain aspects require attention for larger loads or more complex deployments.

**Strengths:**

1.  **Async API (FastAPI/Uvicorn):** Naturally handles concurrent I/O-bound operations (like waiting for LLM responses or database queries) efficiently, allowing the server to manage many simultaneous user requests without blocking.
2.  **Stateless Components (Mostly):** Most agents and utility functions operate based on the input and context provided for each request. This makes it easier to potentially scale API instances horizontally (running multiple copies behind a load balancer), assuming the state management is addressed.
3.  **Modular Design:** Separation of concerns (API, orchestration, agents, data access, LLM client) allows for individual components to be optimized or potentially scaled independently if needed (though less relevant in the current monolithic structure).
4.  **Prisma Client:** Provides connection pooling (configurable) which helps manage database connections efficiently under load.

**Potential Bottlenecks & Scaling Strategies:**

1.  **LLM API Calls:**
    *   **Latency:** LLM responses can take seconds. This is inherent. Using faster models (if available/suitable) or optimizing prompts can help slightly. Streaming responses for long generations (interpretation) can improve perceived performance.
    *   **Rate Limits/Cost:** Heavy usage can hit API rate limits or incur significant costs. Implement robust retry logic (`llm/client.py`), consider caching identical LLM requests (if applicable), and monitor usage closely. Potentially explore fine-tuning smaller models for specific tasks (like classification or validation) if cost becomes prohibitive.
2.  **Database (SQLite):**
    *   **Concurrency:** SQLite handles writes sequentially (database-level lock). While reads can be concurrent, heavy write operations (if added later) or extremely high concurrent reads on a single file can become a bottleneck.
    *   **Scaling:** SQLite is not designed for high-concurrency, large-scale distributed environments. **Strategy:** For significantly larger scale, migrate the database backend (supported by Prisma) to PostgreSQL or MySQL. This would require changing the `datasource` in `schema.prisma` and the `DATABASE_URL`.
3.  **In-Memory State (`WORKFLOW_STATE_STORE`):**
    *   **Volatility:** State is lost on restart.
    *   **Scalability:** Does not work with multiple API instances, as each instance would have its own separate state.
    *   **Strategy:** Replace the in-memory dictionary with an external, persistent state store like Redis (for caching/fast lookups) or store session state directly in the database (e.g., a `WorkflowSession` table managed by Prisma). This is crucial for horizontal scaling and reliability.
4.  **Synchronous Operations:** While the API is async, ensure long-running CPU-bound tasks (if any were added) are run in separate threads or processes (e.g., using FastAPI's `run_in_threadpool`) to avoid blocking the main async event loop. The current LLM calls and DB queries are I/O bound and handled well by `asyncio`.
5.  **Resource Usage:** Monitor CPU and memory usage, especially of the LLM client and data processing steps (like dataset analysis). Optimize code or provide more resources as needed.

**Future Scalability Path:**

1.  **Implement Persistent State:** Replace `WORKFLOW_STATE_STORE` with Redis or a DB table.
2.  **Horizontal Scaling:** Deploy multiple instances of the FastAPI application behind a load balancer (requires persistent state).
3.  **Database Migration:** If SQLite limits are reached, migrate to PostgreSQL/MySQL using Prisma's migration tools.
4.  **(Optional) Message Queue:** For very long-running tasks (e.g., complex analysis or batch processing), consider introducing a message queue (like Celery with RabbitMQ/Redis) to decouple task execution from the API request/response cycle.
5.  **Optimize Prompts/Models:** Continuously refine prompts and potentially use smaller/faster LLMs for specific, simpler tasks.
