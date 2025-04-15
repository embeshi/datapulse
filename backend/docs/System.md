```
+-------------------------------------------------------------------------------------------------+
|                                         SETUP PHASE                                             |
+-------------------------------------------------------------------------------------------------+
|                                                                                                 |
|  [CSV Files] ---> [Sampler] ---> [SchemaSuggest] ---> [LLMClientSetup] ---> [SchemaSuggest]     |
|      ^              (src)           (src)                 (src)                 (src)           |
|      |                                |                     ^                     |             |
|      |                                | (Prompt)            | (API Key)           | (Suggestion)|
|      |                                v                     |                     v             |
|      +<----[DataLoader]<----[SchemaScript]<----[Schema]<----[SchemaScript]<----[SchemaSuggest]   |
|      |      (src)             (scripts)       (prisma)       (scripts)           (src)           |
|      |      (Reads)           (Trigger Load)  (User Edit)    (Save Suggestion)                   |
|      |                                |                     ^                                   |
|      |                                | (Run Generate/Push) | (User Confirmed)                  |
|      v                                v                     |                                   |
|  [SQLite DB] <----[Prisma CLI]<-------+---------------------+                                   |
|  (analysis.db)    (External)                                                                    |
|      ^                                                                                          |
|      | (Writes)                                                                                 |
|      +----[DataLoader]                                                                          |
|             (src)                                                                               |
|                                                                                                 |
|  (Optional Analysis)                                                                            |
|  [SQLite DB] ---> [DatasetAnalyzer] ---> [LLMClientSetup] ---> [DatasetAnalyzer] ---> [Analysis Results] |
|      ^              (src)                   (src)                 (src)              (analysis_results/*)|
|      |              (Reads)                 (Prompt)              (Writes)                           |
|      +<----[SchemaScript]                                                                       |
|             (scripts)                                                                           |
|             (Trigger Analysis?)                                                                 |
|                                                                                                 |
+-------------------------------------------------------------------------------------------------+

+-------------------------------------------------------------------------------------------------+
|                                         RUNTIME PHASE                                           |
+-------------------------------------------------------------------------------------------------+
|                                                                                                 |
|  [User] ---> [FastAPI App] ---> [Router] ---> [Orchestrator] ---> [ContextProvider] ---> [Schema] |
|              (src/api)          (src/api)      (src)              (src/prisma_utils)    (prisma)|
|                                                   ^                     | (Reads)               |
|                                                   | (Context String)    v                       |
|                                                   +------------------- [SQLite DB] <------------+
|                                                   |                     (analysis.db)           |
|                                                   |                     ^         ^             |
|                                                   | (Reads)             | (Reads) |             |
|                                                   +---------------------+---------+             |
|                                                   |                                             |
|                                                   | ---> [IntentClassifier] ---> [LLMClientRuntime] |
|                                                   |      (src/utils)           (src/llm)          |
|                                                   |         ^                                     |
|                                                   | (Intent)|                                     |
|                                                   +---------+                                     |
|                                                   |                                             |
|  (Route based on Intent)                          |                                             |
|  /----------------+----------------\              |                                             |
|  | Descriptive    | Analytical     | Specific     |                                             |
|  v                v                v              |                                             |
| [Describer]    [Planner]        [Planner] <-------+                                             |
| (in Orch.)     (Insights Mode)  (Plan Mode)                                                     |
|  |                |                |                                                             |
|  v (Description)  v (Suggestions)  v (Initial Plan)                                             |
| [Orchestrator] -> [Router] -> [User] | -> [Orchestrator] -> [Validator] -> [Orchestrator]        |
|                                      |                     (src/agents)      |                   |
|                                      |                                       v (Validated Plan)  |
|                                      +-------------------------------------> [SQLGenerator]      |
|                                                                              (src/agents)        |
|                                                                                | (Generated SQL)   |
|                                                                                v                   |
|                                                                              [Orchestrator] ----> [StateStore] |
|                                                                                |                   (In-Memory) |
|                                                                                v (SQL + SessionID) |
|                                                                              [Router] ----------> [User]       |
|                                                                                |                  (Review SQL)|
|                                                                                v (Execute Request)|
|                                                                              [Orchestrator] <---- [User]       |
|                                                                                | (Execute Phase)  (Approved SQL)|
|                                                                                |                  ^             |
|                                                                                v                  |             |
|                                                                              [SQLExecutor] -----> [SQLite DB]  |
|                                                                              (src/prisma_utils)   ^             |
|                                                                                | (Results/Error)  |             |
|                                                                                v                  |             |
|                                                                              [Orchestrator] ------+             |
|                                                                                |        |                       |
|                                                               (If Error)       |        | (If Success)          |
|                                                                        v        |        v                       |
|                                                                     [SQLDebugger] |      [Interpreter]         |
|                                                                     (src/agents)  |      (src/agents)          |
|                                                                        |        |        |                       |
|                                                                        v        |        v                       |
|                                                                     [Orchestrator] <------+                       |
|                                                                        | (Final Result/Error)                 |
|                                                                        v                                      |
|                                                                      [Router] ----------> [User]              |
|                                                                                                               |
+-------------------------------------------------------------------------------------------------+
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
