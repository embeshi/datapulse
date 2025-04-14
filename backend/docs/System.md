+----------------------------+
                  |    Data Loader (Python)    |
                  +-------------^--------------+
                                | (Loads Data)
( CSV/Files ) --> -------------+
                                |
+---------------------------------------------------------------------------------+
|                                     CORE SYSTEM                                     |
|                                                                                 |
|   +--------------------------+        +-------------------------+        +-----------------------+   |
|   | DB Schema Provider (Det.)| <----->|   SQLite Database       | <----->| SQL Executor (SQLAlchemy)| |
|   +----------^---------------+        |   (Data + History Meta) |        +---------^-----+---------+   |
|              | (Schema Info)          +-----------^-------------+                  |     | (Results) |
|              |                                    | (Execute SQL)                  |     |             |
|   +----------+------------------------------------+-----------+--------------------+-----+-----------+   |
|   |                  +---------------------------------------+ |                            |             |
|   |                  |         Interpreter Agent (LLM)         | <-- Request/State/Results --> ( User )   |
|   |                  | (Orchestration, Understand, Interpret)| |<---- Response/UI Action ---+             |
|   |                  +----^--------+--------^--------+-------+ |                                          |
|   | (Asks For Plan)     |        |        |        | (SQL Approved)                                     |
|   |                     v        |        |        |                                                    |
|   | +-------------------+----+   |        |        | +-----------------+                                  |
|   | | Planning Agent (LLM) |<--+        |        | | (Triggers Exec.)|                                  |
|   | +---------^----------+              |        | +-------^---------+                                  |
|   | (Conceptual Plan) |                 |        |         |                                          |
|   |           +-------------------------+        |         +------------------------------------------+   |
|   |                                              |                                                    |
|   | (Asks for SQL) +-----------------------------+                                                    |
|   |                |                                                                                  |
|   |                v                                                                                  |
|   | +--------------------------+                                                                      |
|   | | SQL Generation Agent(LLM)|                                                                      |
|   | +------------^-------------+                                                                      |
|   | (Generated SQL)|                                                                                  |
|   |              +----------------------------------------------------------+                         |
|   |                                                                         |                         |
|   |                               +-----------------------------------------+----+                      |
|   |                               |         SQL Review & Interaction (UI/Logic)  | <-- View/Edit/Approve-- ( User )   |
|   |                               +--------------------^-------------------------+ |<-- History Data ----+            |
|   |                                                    |                           |                     |            |
|   +----------------------------------------------------+---------------------------+---------------------+------------+
|                                                        | (Logs State/Artifacts)                          |
|                                +-----------------------+---------------------------+                     |
|                                |                                                   |                     |
|                      +---------v-------------------------+                         |                     |
|                      | State & History Manager (DB/Logs) | ------------------------+                     |
|                      +-----------------------------------+                                               |
|                                                                                 |
+---------------------------------------------------------------------------------+

Key:
* `( Entity )`: External elements like User or source files.
* `[ Component Name ]`: Internal architectural components.
* `(LLM)`: Component primarily driven by a Large Language Model.
* `(Det.)`: Component primarily driven by deterministic code.
* `(SQLAlchemy)`: Component specifically using SQLAlchemy.
* `-->`, `<--`, `<-->`: Direction of primary data or control flow.
* `(...Label...)`: Description of the data/action on the arrow.
* `----->| Logs...`: Dotted or secondary lines showing logging to the History Manager.

**Flow Highlights:**

1.  Data is loaded into the SQLite DB.
2.  User asks a question, Interpreter gets schema info.
3.  Interpreter orchestrates Planning -> SQL Generation (LLMs).
4.  **Crucially**, generated SQL goes to the **SQL Review & Interaction** component.
5.  User interacts (views, potentially edits, approves) the SQL.
6.  *Approved* SQL goes back via the Interpreter to the **SQL Executor**.
7.  SQL Executor runs the query against the SQLite DB via SQLAlchemy.
8.  Results return to the Interpreter for translation back to the user.
9.  The **State & History Manager** logs artifacts throughout, enabling transparency and time-travel via the UI.