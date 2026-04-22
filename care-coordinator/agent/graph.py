"""
LangGraph state graph for the Care Coordinator Assistant.

LangGraph provides a checkpointed agent↔tools cycle with conditional edges,
eliminating the need for a manual tool loop or external session storage.

GRAPH TOPOLOGY
  [START] → agent_node → (tool calls?) → guard_booking / tools_node ─┐
                │                                                       │
                └──── (no tool calls) → [END] ←────────────────────────┘

  agent_node:    calls the LLM, gets back text or tool-call requests
  guard_booking: enforces explicit nurse confirmation before book_appointment
  tools_node:    executes requested tools via executor.run()
  should_continue: conditional edge — routes to tools, guard_booking, or END

STATE
  CareState (TypedDict) is the single source of truth.
  MemorySaver checkpoints it per thread_id (= session_id) automatically,
  so stateless HTTP handlers get persistent conversations for free.

PUBLIC API
  make_graph(db) → CompiledStateGraph
      Call once at startup.  Pass the compiled graph to orchestrator.set_graph().
"""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Annotated, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent.prompts import SYSTEM_PROMPT
from tools.schemas import (
    VerifyPatientArgs,
    LookupProviderArgs,
    GetBookingHistoryArgs,
    FindAvailableSlotsArgs,
    CheckProviderAvailabilityArgs,
    ListAlternativeProvidersArgs,
    BookAppointmentArgs,
    VerifyInsuranceArgs,
    GetSelfpayRateArgs,
)

load_dotenv()

# Hard cap on tool calls per conversation turn.
# Prevents infinite loops if the LLM keeps requesting tools without converging.
MAX_TOOL_CALLS = 10


def _is_rate_limit(exc: Exception) -> bool:
    """Return True if the exception is a provider rate-limit / queue-full error."""
    msg = str(exc).lower()
    return "429" in msg or "too_many_requests" in msg or "queue_exceeded" in msg

# PHI fields stripped from tool results before they enter the LLM message
# history.  MemorySaver checkpoints the full message list, so any field
# we leave in will be persisted and replayed to the LLM on every future turn.
# Single source of truth lives in safety/phi.py.
from safety.phi import PHI_STRIP_MAP as _PHI_STRIP


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class CareState(TypedDict):
    """Consolidates conversation history, workflow state, and patient context
    into one checkpointed structure.

    The `messages` field uses LangGraph's add_messages reducer, which appends
    new messages rather than replacing the whole list on each state update.
    """
    messages: Annotated[list, add_messages]  # full conversation history
    patient_id: Optional[int]                # set after verify_patient succeeds
    patient_confirmed: bool                  # True once identity is verified
    workflow_state: str                      # WorkflowState enum value ("greet", …)
    referrals: list                          # list of referral dicts (one per referral)
    active_referral_index: int               # which referral is currently being booked
    completed_bookings: list                 # confirmation numbers already issued
    tool_call_count: int                     # resets to 0 at start of each turn
    last_booking_confirmation: Optional[str] # for booking cross-check in orchestrator


# ---------------------------------------------------------------------------
# LangChain tool stubs
#
# These StructuredTool objects are ONLY used to generate the JSON Schema
# that llm.bind_tools() sends to the model in the system message.
# Actual execution happens in tools_node via executor.run(), which enforces
# permission checks, input validation, and audit logging.
# ---------------------------------------------------------------------------

def _lc_stub(name: str, description: str, args_schema) -> StructuredTool:
    """Thin wrapper: creates a no-op StructuredTool whose only job is schema."""
    return StructuredTool.from_function(
        func=lambda **_: None,
        name=name,
        description=description,
        args_schema=args_schema,
    )


# One stub per tool.  The description here is what the LLM reads when deciding
# which tool to call — keep it directive (ALWAYS, ONLY, IMPORTANT) so the model
# follows the intended workflow order.
_LC_TOOLS = [
    _lc_stub(
        "verify_patient",
        "Search for a patient by name and/or date of birth to verify their identity. "
        "ALWAYS call this first — before any patient-specific action.",
        VerifyPatientArgs,
    ),
    _lc_stub(
        "lookup_provider_info",
        "Find providers by name, specialty, or location/hospital name. ALWAYS call "
        "this tool when the nurse asks about a provider's location, who works at a "
        "hospital, or any provider contact info — never answer from memory. "
        "Returns provider IDs, departments, locations, office hours, and contact info.",
        LookupProviderArgs,
    ),
    _lc_stub(
        "get_booking_history",
        "Check whether a patient has seen a specific provider before and determine "
        "the correct appointment type (NEW or ESTABLISHED). "
        "ALWAYS call this before searching for slots — it tells you the required duration.",
        GetBookingHistoryArgs,
    ),
    _lc_stub(
        "find_available_slots",
        "Search for available appointment slots for a provider at a given location. "
        "Filter by duration: use 30 for NEW patients, 15 for ESTABLISHED. "
        "Returns up to 40 slots grouped by day. "
        "IMPORTANT: always search the full default window (today → 28 days). "
        "Do NOT narrow the date range to match a time-of-day preference.",
        FindAvailableSlotsArgs,
    ),
    _lc_stub(
        "check_provider_availability",
        "Get a provider's full schedule profile: all departments, locations, and office hours. "
        "Use this when you have a provider_id but need to know which location_id to use "
        "before calling find_available_slots. Never guess a location_id. "
        "If the nurse asks about 'he' or 'she' or 'this provider', use the provider_id "
        "already known from the current conversation — do not ask for clarification.",
        CheckProviderAvailabilityArgs,
    ),
    _lc_stub(
        "list_alternative_providers",
        "Find other providers in the same specialty when the preferred provider "
        "is unavailable or has no open slots at the requested time. "
        "Pass patient_id and duration to get next available slots and patient history "
        "for each alternative — use this to give the nurse instant 'No, but...' alternatives.",
        ListAlternativeProvidersArgs,
    ),
    _lc_stub(
        "book_appointment",
        "FINALIZE an appointment booking after the nurse has explicitly confirmed. "
        "ONLY call this after the nurse says 'yes', 'confirm', 'book it', or similar. "
        "This action is irreversible — it marks the slot as taken and issues a confirmation number.",
        BookAppointmentArgs,
    ),
    _lc_stub(
        "verify_insurance",
        "ALWAYS call this tool to check whether a patient's insurance plan is accepted. "
        "Never answer insurance questions from memory — plans and acceptance status "
        "must come from this tool. Returns the canonical plan name and accepted status.",
        VerifyInsuranceArgs,
    ),
    _lc_stub(
        "get_selfpay_rate",
        "ALWAYS call this tool to get out-of-pocket costs when insurance is not accepted. "
        "Never guess or estimate self-pay rates — they must come from this tool.",
        GetSelfpayRateArgs,
    ),
]


# ---------------------------------------------------------------------------
# Helpers: LangGraph state ↔ tool session dict
#
# Tools operate on a flat session dict. These helpers bridge between the
# typed graph state and the tool interface.
# ---------------------------------------------------------------------------

def _blank_referral() -> dict:
    """Default referral dict — one slot in the referrals list per booking."""
    return {
        "specialty": None,
        "provider_id": None,
        "location_id": None,
        "appointment_type": None,
        "slot_id": None,
        "insurance_verified": False,
        "booked": False,
        "confirmation_number": None,
    }


def _state_to_session(state: CareState) -> dict:
    """Build the legacy session dict that executor.run() passes to tool classes.

    We deep-copy mutable sub-structures (referrals, completed_bookings) so that
    tool mutations to the session dict don't silently alias into CareState.
    Mutations are read back explicitly in _apply_session_mutations().
    """
    from core.workflow import WorkflowState
    ws_str = state.get("workflow_state", "greet")
    try:
        ws_enum = WorkflowState(ws_str)
    except ValueError:
        ws_enum = WorkflowState.GREET

    return {
        "session_id":           "langgraph",          # placeholder, not used by tools
        "state":                ws_enum,
        "patient_id":           state.get("patient_id"),
        "patient_confirmed":    state.get("patient_confirmed", False),
        "referrals":            copy.deepcopy(state.get("referrals", [])),
        "active_referral_index": state.get("active_referral_index", 0),
        "completed_bookings":   copy.deepcopy(state.get("completed_bookings", [])),
        "created_at":           "",
    }


def _apply_session_mutations(session: dict, state: CareState) -> dict:
    """Return CareState key updates for any values the tool mutated in session.

    Only fields that actually changed are included, keeping state updates minimal.
    """
    updates: dict = {}

    if session.get("patient_id") != state.get("patient_id"):
        updates["patient_id"] = session["patient_id"]

    if session.get("patient_confirmed") != state.get("patient_confirmed", False):
        updates["patient_confirmed"] = session["patient_confirmed"]

    # referrals list is mutated by verify_patient (adds first referral) and
    # by book_appointment (marks a referral as booked).
    if session.get("referrals") != state.get("referrals"):
        updates["referrals"] = session["referrals"]

    if session.get("active_referral_index") != state.get("active_referral_index", 0):
        updates["active_referral_index"] = session["active_referral_index"]

    if session.get("completed_bookings") != state.get("completed_bookings", []):
        updates["completed_bookings"] = session["completed_bookings"]

    return updates


def _workflow_transition(
    tool_name: str, result: dict, current_ws: str, state: CareState
) -> dict:
    """Map a tool result to workflow_state updates.

    Returns a partial CareState dict with only the keys that should change.

    Transition table:
      verify_patient (found)        → collect_referral
      find_available_slots (slots)  → check_availability
      verify_insurance              → verify_insurance
      book_appointment (success)    → booking_confirmed
    """
    updates: dict = {}

    if tool_name == "verify_patient" and result.get("found"):
        updates["workflow_state"] = "collect_referral"
        # Seed the first referral slot so tools don't have to check for None.
        if not state.get("referrals"):
            updates["referrals"] = [_blank_referral()]
            updates["active_referral_index"] = 0

    elif tool_name == "find_available_slots" and result.get("slots"):
        # Only advance if we're in the referral-gathering stages.
        if current_ws in ("collect_referral", "determine_appt_type"):
            updates["workflow_state"] = "check_availability"

    elif tool_name == "verify_insurance":
        if current_ws == "check_availability":
            updates["workflow_state"] = "confirm_booking"

    elif tool_name == "book_appointment" and result.get("success"):
        updates["workflow_state"] = "booking_confirmed"
        # Persist confirmation number so the orchestrator can cross-check it
        # against the text the LLM writes (prevents hallucinated conf numbers).
        updates["last_booking_confirmation"] = result.get("confirmation_number")

    return updates


def _phi_strip(tool_name: str, result: dict) -> dict:
    """Remove PHI fields from a tool result before it enters LLM message history."""
    keys = _PHI_STRIP.get(tool_name, set())
    return {k: v for k, v in result.items() if k not in keys} if keys else result


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def make_graph(db: dict):
    """Build and compile the LangGraph state graph.

    Args:
        db: In-memory database dict from load_all_data().  Captured by closure
            inside tools_node so the large Provider/Slot objects are never
            serialised into the MemorySaver checkpoint.

    Returns:
        Compiled LangGraph graph.  Pass this to orchestrator.set_graph().
    """
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CEREBRAS_API_KEY is not set. "
            "Add it to your .env file or export it in your shell."
        )

    # ChatOpenAI with the Cerebras-hosted Qwen model.
    # temperature=0 for deterministic, audit-friendly responses in a clinical context.
    llm = ChatOpenAI(
        model="qwen-3-235b-a22b-instruct-2507",
        openai_api_base="https://api.cerebras.ai/v1",
        openai_api_key=api_key,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(_LC_TOOLS)

    # Fallback LLM — same provider/model, separate API key.
    # Used when the primary key hits a 429 queue limit.
    fallback_api_key = os.environ.get("CEREBRAS_API_KEY_FALLBACK")
    llm_fallback_with_tools = None
    if fallback_api_key:
        llm_fallback = ChatOpenAI(
            model="qwen-3-235b-a22b-instruct-2507",
            openai_api_base="https://api.cerebras.ai/v1",
            openai_api_key=fallback_api_key,
            temperature=0,
        )
        llm_fallback_with_tools = llm_fallback.bind_tools(_LC_TOOLS)

    # Import executor here so all tool packages self-register via their
    # registry.register() calls at module load time.
    from tools import executor as _executor

    # ------------------------------------------------------------------
    # Node: agent
    # Prepend the system prompt on every call — LangGraph does not persist
    # SystemMessages between turns, so we inject it fresh each time.
    # ------------------------------------------------------------------

    def agent_node(state: CareState) -> dict:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
        try:
            response = llm_with_tools.invoke(messages)
        except Exception as exc:
            if llm_fallback_with_tools and _is_rate_limit(exc):
                response = llm_fallback_with_tools.invoke(messages)
            else:
                raise
        # Returning {"messages": [response]} triggers add_messages, which
        # appends the new AIMessage to the existing history.
        return {"messages": [response]}

    # ------------------------------------------------------------------
    # Node: tools
    # Executes every tool_call in the last AIMessage.  One message can
    # contain multiple parallel tool calls (e.g. lookup + history check).
    # ------------------------------------------------------------------

    def tools_node(state: CareState) -> dict:
        last_msg = state["messages"][-1]
        tool_messages = []   # ToolMessage per call, returned as new messages
        state_updates: dict = {}
        current_ws = state.get("workflow_state", "greet")
        calls_this_turn = 0

        for tc in last_msg.tool_calls:
            name    = tc["name"]
            args    = tc["args"]
            call_id = tc["id"]

            # Build a fresh session dict for this tool call.
            # Tools mutate this dict (e.g. set patient_id, append referrals);
            # we read mutations back via _apply_session_mutations().
            session = _state_to_session(state)

            # executor.run: permission check → input validation → execute → log.
            # Returns JSON string.
            result_str = _executor.run(name, args, db, session)

            # Flush any session mutations back into the pending state update.
            state_updates.update(_apply_session_mutations(session, state))

            # Parse the JSON result so we can inspect it for workflow transitions.
            try:
                result = json.loads(result_str)
            except Exception:
                result = {"result": result_str}

            # Advance the workflow state if this tool result warrants it.
            transition_updates = _workflow_transition(name, result, current_ws, state)
            state_updates.update(transition_updates)
            # Keep current_ws in sync for subsequent tool calls within this turn
            # (e.g. verify_patient then find_slots in the same LLM message).
            if "workflow_state" in transition_updates:
                current_ws = transition_updates["workflow_state"]

            # Strip PHI before the result enters the message history that
            # MemorySaver will checkpoint and replay to the LLM on future turns.
            result_for_llm = _phi_strip(name, result) if isinstance(result, dict) else result

            # ToolMessage ties back to the AIMessage by call_id so the LLM
            # can match each result to the tool call that produced it.
            tool_messages.append(ToolMessage(
                content=json.dumps(result_for_llm),
                tool_call_id=call_id,
                name=name,
            ))
            calls_this_turn += 1

        state_updates["messages"] = tool_messages
        # Accumulate the running count so should_continue can enforce MAX_TOOL_CALLS.
        state_updates["tool_call_count"] = (
            state.get("tool_call_count", 0) + calls_this_turn
        )
        return state_updates

    # ------------------------------------------------------------------
    # Conditional edge: should_continue
    # Runs after agent_node.  Returns "tools", "guard_booking", or END.
    # ------------------------------------------------------------------

    def should_continue(state: CareState) -> str:
        # Hard stop: if we've hit the turn limit, force END even if the LLM
        # is still requesting tools.  Prevents runaway loops.
        if state.get("tool_call_count", 0) >= MAX_TOOL_CALLS:
            return END
        last_msg = state["messages"][-1]
        if not (isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None)):
            return END

        # If the LLM wants to book, check explicit nurse confirmation first.
        tool_names = [tc["name"] for tc in last_msg.tool_calls]
        if "book_appointment" in tool_names:
            return "guard_booking"

        return "tools"

    # ------------------------------------------------------------------
    # Node: guard_booking
    # Enforces that the nurse has explicitly confirmed before book_appointment
    # executes.  Runs in Python — zero LLM tokens spent.
    #
    # When workflow_state == "confirm_booking", the guard scans the most
    # recent HumanMessage for confirmation keywords.  If found, it advances
    # the state to "execute_booking" and lets the call proceed to tools_node.
    # If not found, it returns error ToolMessages for ALL pending tool calls
    # (not just book_appointment) so the LLM receives a response for every
    # call it made — preventing undefined behavior from orphaned tool calls.
    # ------------------------------------------------------------------

    _CONFIRM_RE = re.compile(
        r"\b(yes|confirm|book\s*it|go\s*ahead|proceed|please\s*book|approved|affirmative)\b",
        re.IGNORECASE,
    )

    def guard_booking(state: CareState) -> dict:
        ws = state.get("workflow_state", "greet")
        if ws != "confirm_booking":
            return {}

        # Check the most recent HumanMessage for confirmation keywords.
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                if _CONFIRM_RE.search(msg.content):
                    return {"workflow_state": "execute_booking"}
                break

        # Nurse has not confirmed — block ALL tool calls in this AIMessage.
        last_msg = state["messages"][-1]
        error_messages = []
        for tc in last_msg.tool_calls:
            if tc["name"] == "book_appointment":
                error_messages.append(ToolMessage(
                    content=json.dumps({
                        "error": "Explicit nurse confirmation is required before booking. "
                                 "Present the appointment summary and wait for the nurse "
                                 "to say 'yes', 'confirm', 'book it', or similar."
                    }),
                    tool_call_id=tc["id"],
                    name="book_appointment",
                ))
            else:
                error_messages.append(ToolMessage(
                    content=json.dumps({
                        "error": f"Tool '{tc['name']}' is blocked while booking "
                                 "confirmation is pending."
                    }),
                    tool_call_id=tc["id"],
                    name=tc["name"],
                ))
        return {"messages": error_messages}

    def _should_execute_booking(state: CareState) -> str:
        """Route after guard_booking: execute if confirmed, else back to agent."""
        ws = state.get("workflow_state", "greet")
        return "agent" if ws == "confirm_booking" else "tools"

    # ------------------------------------------------------------------
    # Assemble and compile the graph
    # ------------------------------------------------------------------

    graph = StateGraph(CareState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("guard_booking", guard_booking)
    graph.set_entry_point("agent")
    # After agent_node: route to tools, guard_booking, or END.
    graph.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "guard_booking": "guard_booking", END: END}
    )
    # After guard_booking: either proceed to tools (confirmed) or back to agent (blocked).
    graph.add_conditional_edges(
        "guard_booking", _should_execute_booking,
        {"tools": "tools", "agent": "agent"}
    )
    # After tools_node: always go back to agent for the next LLM call.
    graph.add_edge("tools", "agent")

    # MemorySaver stores the full CareState dict keyed by thread_id (= session_id).
    # Each call to graph.invoke() with the same thread_id resumes from where it left off.
    return graph.compile(checkpointer=MemorySaver())
