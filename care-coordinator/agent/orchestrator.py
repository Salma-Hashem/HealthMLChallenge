"""
Orchestrator for the Care Coordinator Assistant.

RESPONSIBILITIES
This module is a thin safety-and-audit wrapper around the LangGraph graph.
It handles concerns that live OUTSIDE the conversation graph:

  Input guardrails    — block prompt injection and oversized messages
  Output guardrails   — detect PHI leakage and medical-advice flags in responses
  Booking cross-check — confirm that any conf number in the text matches the DB record
  Audit logging       — structured log entries for every significant event

Everything INSIDE the graph (LLM calls, tool loop, workflow state transitions,
conversation memory) is handled by agent/graph.py / LangGraph.

ENTRY POINT
  handle_message() is the only public function.  main.py calls it on every POST /api/chat.
  set_graph() must be called once at startup (from main.py) before handle_message() works.

NOTE
  _phi_strip_for_llm() is kept here because tests/eval.py imports it directly.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage

from safety import audit
from safety.guardrails import (
    InputBlocked,
    check_input,
    check_output,
    friendly_blocked_message,
    sanitize_output,
    verify_booking_in_response,
)
from core.workflow import WorkflowState

load_dotenv()

# ---------------------------------------------------------------------------
# Graph reference
#
# Stored in a mutable list so main.py can replace it after DB load without
# requiring a module re-import.  The list always holds at most one item.
# ---------------------------------------------------------------------------

_graph_ref: list = []


def set_graph(compiled_graph) -> None:
    """Register the compiled LangGraph graph.  Called once from main.py."""
    _graph_ref.clear()
    _graph_ref.append(compiled_graph)


def _get_graph():
    """Return the registered graph, raising if set_graph() wasn't called yet."""
    if not _graph_ref:
        raise RuntimeError(
            "Graph not initialised.  Call orchestrator.set_graph(make_graph(db)) "
            "before handle_message()."
        )
    return _graph_ref[0]


# ---------------------------------------------------------------------------
# PHI minimisation
#
# PHI fields stripped from tool results before they enter LLM context.
# Used by the eval harness for PHI assertion tests.
# ---------------------------------------------------------------------------

from safety.phi import PHI_STRIP_MAP as _PHI_STRIP_MAP
from agent.graph import _is_rate_limit as _is_rate_limit_error


def _phi_strip_for_llm(tool_name: str, result: dict) -> dict:
    """Return result with PHI keys removed.  Used by tests/eval.py to test PHI handling."""
    strip_keys = _PHI_STRIP_MAP.get(tool_name, set())
    if not strip_keys:
        return result
    return {k: v for k, v in result.items() if k not in strip_keys}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def handle_message(
    session_id: Optional[str],
    user_message: str,
    db: dict,
    regenerate: bool = False,
) -> dict:
    """Process one user message and return the assistant response + metadata.

    Flow:
      1. Input guardrail  — block prompt injection / oversized messages
      2. Assign session ID — generate UUID for new conversations
      3. Regeneration     — drop the last AI turn before re-invoking (if requested)
      4. Reset counter    — zero the per-turn tool call counter in stored state
      5. Graph invoke     — LangGraph runs agent → tools → agent until done
      6. Parse result     — extract final text, tool names, booking conf number
      7. Output guardrail — flag PHI leakage or medical advice in the response
      8. Booking check    — redact conf number if it doesn't match the DB record

    Args:
        session_id:   Existing thread ID, or None to start a new conversation.
        user_message: Raw user text.
        db:           In-memory database (passed through to the graph closure).
        regenerate:   If True, drop the last AI turn and re-run the graph.

    Returns:
        Dict with keys: session_id, response, workflow_state, action_cards,
        requires_confirmation, tool_calls.
    """
    graph = _get_graph()

    trace_id = audit.new_trace_id()
    audit.log_message_received(trace_id, session_id, len(user_message))

    # --- 1. Input guardrail ---
    # Blocks prompt injection attempts, excessively long messages, etc.
    # Returns a safe fallback response rather than raising to the caller.
    try:
        check_input(user_message, session_id or "")
    except InputBlocked as exc:
        audit.log_input_blocked(trace_id, session_id, exc.reason, exc.pattern_key)
        return {
            "session_id":            session_id,
            "response":              friendly_blocked_message(),
            "workflow_state":        "GREET",
            "action_cards":          [],
            "requires_confirmation": False,
        }

    # --- 2. Assign session ID ---
    # New conversations get a UUID; existing sessions reuse their thread_id.
    if not session_id:
        session_id = str(uuid.uuid4())

    # LangGraph uses "configurable.thread_id" to look up the right checkpoint.
    lg_config = {"configurable": {"thread_id": session_id}}

    # --- 3. Regeneration ---
    # Pops the last AI message (and any tool call/result pairs attached to it)
    # so the graph re-generates a fresh response to the same user input.
    if regenerate:
        _pop_last_ai_turn(graph, lg_config)

    # --- 4. Reset per-turn tool call counter ---
    # The counter accumulates inside the graph state; we zero it here so
    # the MAX_TOOL_CALLS cap applies per turn, not across the whole session.
    _reset_tool_call_count(graph, lg_config)

    # --- 5. Invoke the LangGraph graph ---
    # The graph will: load stored state for this thread_id, merge the new
    # HumanMessage, run the agent ↔ tools loop, then checkpoint the final state.
    audit.log_tool_called(trace_id, session_id, "graph.invoke", [])
    try:
        result_state = graph.invoke(
            {"messages": [HumanMessage(content=user_message)]},
            config=lg_config,
        )
    except Exception as exc:
        if _is_rate_limit_error(exc):
            error_msg = "Sorry, wallet is strapped — please try again later."
        else:
            error_msg = (
                "I'm sorry, I encountered an error communicating with the "
                f"AI service. Please try again. (Error: {exc})"
            )
        return _build_response(session_id, {}, error_msg)

    # --- 6. Parse result ---
    # Extract the final assistant text, list of tool names called, and any
    # booking confirmation number found in a ToolMessage.
    final_text, tool_calls_this_turn, last_booking_conf = _parse_result(result_state)

    # Log each individual tool call for the audit trail.
    for name in tool_calls_this_turn:
        audit.log_tool_called(trace_id, session_id, name, [])
        if name == "book_appointment":
            audit.log_booking_attempt(
                trace_id, session_id,
                patient_id=result_state.get("patient_id", "unknown"),
                slot_id="",
                appointment_type="",
            )

    # --- 7. Output guardrail ---
    # Checks the response for PHI patterns or unsupported medical advice.
    # sanitize_output() redacts or rewrites flagged content.
    output_flag = check_output(final_text)
    if not output_flag.is_clean:
        audit.log_output_flagged(trace_id, session_id, output_flag.flags)
        final_text = sanitize_output(final_text, output_flag)

    # --- 8. Booking cross-check ---
    # The LLM might hallucinate a confirmation number that differs from the one
    # the DB actually issued.  If they don't match, replace the number in the
    # response with a safe placeholder.
    booking_conf = last_booking_conf or result_state.get("last_booking_confirmation")
    if not verify_booking_in_response(final_text, booking_conf):
        audit.log_output_flagged(trace_id, session_id, ["booking_confirmation_mismatch"])
        final_text = re.sub(r"\bCCA-[0-9A-F]{8}\b", "[CONFIRMATION PENDING]", final_text)

    audit.log_response_sent(trace_id, session_id, len(final_text))

    return _build_response(session_id, result_state, final_text, tool_calls_this_turn)


# ---------------------------------------------------------------------------
# LangGraph state helpers
# ---------------------------------------------------------------------------

def _pop_last_ai_turn(graph, config: dict) -> None:
    """Remove the last AI message and its associated tool messages from the checkpoint.

    Called before re-invoking the graph for a regenerate request.
    Uses RemoveMessage so the add_messages reducer actually deletes by ID.
    Failure is non-fatal — the graph will just re-append rather than replace.
    """
    try:
        from langgraph.graph.message import RemoveMessage
        from langchain_core.messages import ToolMessage
        snap = graph.get_state(config)
        if snap is None:
            return
        messages = list(snap.values.get("messages", []))
        to_remove = []

        # Collect trailing plain AI response (no tool calls).
        if messages and isinstance(messages[-1], AIMessage):
            to_remove.append(messages.pop())

        # Collect tool result messages and the AI message that triggered them.
        # Pattern: [… AIMessage(tool_calls=[…]), ToolMessage, ToolMessage, …]
        while messages:
            if isinstance(messages[-1], ToolMessage):
                to_remove.append(messages.pop())
            elif isinstance(messages[-1], AIMessage) and getattr(messages[-1], "tool_calls", None):
                to_remove.append(messages.pop())
            else:
                break

        if to_remove:
            graph.update_state(config, {"messages": [RemoveMessage(id=m.id) for m in to_remove]})
    except Exception:
        pass  # Non-fatal: worst case the user sees the old response again


def _reset_tool_call_count(graph, config: dict) -> None:
    """Zero the per-turn tool call counter in the checkpoint before each invoke.

    This ensures MAX_TOOL_CALLS is enforced per conversation turn, not
    cumulatively across the whole session.
    """
    try:
        graph.update_state(config, {"tool_call_count": 0})
    except Exception:
        pass  # Non-fatal: the field starts at 0 anyway for brand-new sessions


def _parse_result(result_state: dict) -> tuple[str, list[str], Optional[str]]:
    """Extract the final assistant text, tool names called, and booking confirmation.

    Only scans messages from the current turn — everything after the last
    HumanMessage — so tool_names and booking_conf are not polluted by prior turns.
    """
    from langchain_core.messages import ToolMessage

    messages = result_state.get("messages", [])
    final_text = ""
    tool_names: list[str] = []
    booking_conf: Optional[str] = None

    # Find the index of the last HumanMessage — that's the turn boundary.
    turn_start = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            turn_start = i + 1  # current turn starts after the last human message

    for msg in messages[turn_start:]:
        if isinstance(msg, AIMessage):
            if msg.content:
                final_text = msg.content
            for tc in getattr(msg, "tool_calls", []):
                tool_names.append(tc["name"])

        if isinstance(msg, ToolMessage) and msg.name == "book_appointment":
            try:
                data = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                if isinstance(data, dict) and data.get("confirmation_number"):
                    booking_conf = data["confirmation_number"]
            except Exception:
                pass

    return final_text, tool_names, booking_conf


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _build_response(
    session_id: str,
    state: dict,
    text: str,
    tool_calls: Optional[list] = None,
) -> dict:
    """Assemble the JSON dict returned to the frontend by POST /api/chat."""
    ws_str = state.get("workflow_state", "greet")
    try:
        ws_enum = WorkflowState(ws_str)
    except ValueError:
        ws_enum = WorkflowState.GREET

    return {
        "session_id":            session_id,
        "response":              text,
        # Expose the enum value string (e.g. "booking_confirmed") so the
        # frontend can update its progress indicator without parsing the text.
        "workflow_state":        (ws_enum.value if hasattr(ws_enum, "value") else str(ws_enum)).upper(),
        "action_cards":          [],
        # Drives the "Confirm booking?" UI prompt in the frontend.
        "requires_confirmation": ws_enum == WorkflowState.CONFIRM_BOOKING,
        "tool_calls":            tool_calls or [],
    }
