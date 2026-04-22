"""
Target function for LangSmith evaluation.

run_conversation(inputs) is the function passed to langsmith.evaluate(target=...).
It runs a full multi-turn conversation through the Care Coordinator stack and
returns a structured dict that evaluators can inspect.

IMPORTANT DESIGN DECISIONS

1. Fresh DB per call
   Each test case loads a new in-memory DB and generates new slots so that
   one test's booking doesn't affect the next (slots are marked unavailable
   after booking).

2. Full stack (not graph-only)
   We call orchestrator.handle_message() rather than the graph directly so
   that guardrails, PHI stripping, and booking cross-checks are all exercised.

3. Sequential evaluation (max_concurrency=1 in test_llm_evals.py)
   orchestrator._graph_ref is a module-level singleton.  Running multiple
   conversations concurrently would race on set_graph().  Sequential mode is
   correct for a stateful system like this.

4. Accumulated tool calls
   handle_message() returns tool_calls from _parse_result(), which scans the
   full message history on every turn.  We take the LAST turn's tool_calls —
   it already contains every tool called across the entire conversation.

OUTPUTS DICT (what evaluators receive)
  final_response   str        — last assistant message text
  workflow_state   str        — final WorkflowState enum value
  tool_calls       list[str]  — all tool names called (accumulated, deduped-order)
  messages_sent    list[str]  — user messages (for LLM judge context)
  session_id       str        — for debugging in LangSmith traces
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Ensure the project root is on sys.path so imports work whether pytest runs
# from the project root or from inside the tests/ directory.
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_fresh_db() -> dict:
    """Load a clean in-memory DB with freshly generated slots.

    Called at the start of every test case so each conversation starts
    with the full slot inventory available.
    """
    from data.loader import load_all_data
    from core.slots import generate_slots

    data_path = _PROJECT_ROOT / "data" / "data_sheet.txt"
    db = load_all_data(str(data_path))
    db["slots"] = generate_slots(db["providers"], db["departments"], num_days=28)
    return db


def run_conversation(inputs: dict) -> dict:
    """Execute a multi-turn conversation and return observable outputs.

    Args:
        inputs: LangSmith dataset example inputs dict.  Expected keys:
                  messages  — list of user message strings (in order)
                  case_id   — test case identifier (for logging)
                  name      — test case name (for logging)

    Returns:
        Dict consumed by evaluators:
          final_response, workflow_state, tool_calls, messages_sent, session_id
    """
    import agent.orchestrator as orchestrator
    from agent.graph import make_graph

    messages: list[str] = inputs.get("messages", [])
    if not messages:
        return {
            "final_response": "",
            "workflow_state": "greet",
            "tool_calls": [],
            "messages_sent": [],
            "session_id": "",
        }

    # Fresh DB + new compiled graph for this test case.
    # set_graph() replaces the module-level singleton — safe because
    # evaluate() calls run_conversation() sequentially (max_concurrency=1).
    db = _load_fresh_db()
    orchestrator.set_graph(make_graph(db))

    session_id: Optional[str] = None
    result: Optional[dict] = None

    for user_message in messages:
        result = orchestrator.handle_message(
            session_id=session_id,
            user_message=user_message,
            db=db,
        )
        session_id = result["session_id"]

    if result is None:
        return {
            "final_response": "",
            "workflow_state": "greet",
            "tool_calls": [],
            "messages_sent": messages,
            "session_id": "",
        }

    # result["tool_calls"] comes from _parse_result() which scans the full
    # message history — so the last turn's value already includes all tool
    # calls ever made in this conversation.
    return {
        "final_response": result.get("response", ""),
        "workflow_state": result.get("workflow_state", "greet"),
        "tool_calls": result.get("tool_calls", []),
        "messages_sent": messages,
        "session_id": session_id or "",
    }
