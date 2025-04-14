+-------+      +---------------------------------+      +---------+      +------------+      +-----------+      +-----------+
| User  | ---->|       Interpreter Agent         | ---> | Planner | ---->| Programmer | ---->| Execution |      | Validator |
| Input |<---- | (Orchestrator, Router, Context) | <--- | Agent   | <----| Agent      |<---- | Engine    |      | Agent     |
+-------+      +---------------------------------+      +---------+      +------------+      +-----------+      +-----------+
    |                 ^   |        |        |   ^            | |              | |               | |              ^ |
    | Clarify?        |   |        |        |   |            | |              | |               | |              | |
    |<----------------|---|(A) Task| Task   |---|(B) Plan-----| |(D) Code------| |(F) Result/Err-| |--------------| |
    |                 |   | Profile| Plan   |   | w/Schema     | | aiming for   | |---------------| |              | |
    |                 |   |        |(C) Task|   |------------->| | Plan Schema  | |               | |              | |
    |                 |   +--------> Code   |                  +--------------->| |               | |              | |
    |                 |            |        |                                   +---------------->| |Validate this?| |
    |                 |            |        |----------------------------------------------------->| |<-------------| |
    |                 |            |                                                               | | Output       | |
    |                 |            |<--------------------------------(G) Result/Error--------------+ | Schema OK?   | |
    |                 |            |                                                                 | Plan OK?     | |
    |                 |            |<--------------------------------(E) Code/Status----------------+ |--------------| |
    |                 |            |                                                                                | |
    |                 |            |<--------------------------------(C) Plan/Status--------------------------------+ |
    |                 |            |                                                                                | |
    |                 |            |<--------------------------------(A) Profile Data-------------------------------+ |
    |                 |            |                                                                                | |
    |                 |<-----------(H) Validation Result (VALID/INVALID + Details) ----------------------------------+ |
    |                 |            |
    | Result/         |            +-- If VALID: Proceed (e.g., C->D, E->F, G->Interpret)
    | Suggestion      |            |
    |<----------------|------------+-- If INVALID: Route back to source w/ feedback (e.g., H(Plan Invalid)->Planner)
    | Error/          |            |
    | Feedback        |            |
    |                 | Interpret Validated Result
    +---------------->| User Modification / Next Q