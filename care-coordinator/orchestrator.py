"""
Orchestrator for the Care Coordinator Assistant.

Central module connecting Groq (llama-3.3-70b-versatile via OpenAI-compatible
API), tool executors, policy engine, and workflow state machine.
Core entry point: handle_message().
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

import audit_log
import memory
from guardrails import (
    InputBlocked, check_input, check_output, friendly_blocked_message,
    sanitize_output, verify_booking_in_response,
)
from prompts import SYSTEM_PROMPT
from tools import registry, executor as tool_executor
from workflow import (
    WorkflowState, create_session, add_referral, transition_to,
)

load_dotenv()

MODEL = "qwen-3-235b-a22b-instruct-2507"
MAX_TOOL_CALLS = 10


def get_client() -> OpenAI:
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CEREBRAS_API_KEY is not set. "
            "Add it to your .env file or export it in your shell. "
            "Get a free key at https://cloud.cerebras.ai"
        )
    return OpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")


def handle_message(
    session_id: Optional[str],
    user_message: str,
    db: dict,
    sessions: dict,
    regenerate: bool = False,
) -> dict:
    """Process one user message and return the assistant response + metadata."""

    # Assign a trace ID for end-to-end correlation in the audit log.
    trace_id = audit_log.new_trace_id()
    audit_log.log_message_received(trace_id, session_id, len(user_message))

    # 1. Input guardrail — screen before touching session or LLM.
    try:
        check_input(user_message, session_id or "")
    except InputBlocked as exc:
        audit_log.log_input_blocked(trace_id, session_id, exc.reason, exc.pattern_key)
        return {
            "session_id": session_id,
            "response": friendly_blocked_message(),
            "workflow_state": "GREET",
            "action_cards": [],
            "requires_confirmation": False,
        }

    # 2. Load or create session
    if not session_id or session_id not in sessions:
        session = create_session()
        sessions[session["session_id"]] = session
        session_id = session["session_id"]
    else:
        session = sessions[session_id]

    # 2b. Regeneration: pop the previous assistant turn so the LLM re-processes
    # the same user message fresh, without the old response in context.
    if regenerate:
        memory.pop_last_assistant_turn(session_id)

    # 3. Add user message to conversation history
    memory.add_user_message(session_id, user_message)

    # 4. Tool-calling loop
    client = get_client()
    openai_tools = registry.get_openai_tools()
    tool_call_count = 0
    final_text = ""
    last_confirmed_booking: Optional[str] = None
    tool_calls_this_turn: list = []

    while tool_call_count < MAX_TOOL_CALLS:
        messages = memory.get_messages(session_id)
        all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=all_messages,
                tools=openai_tools,
                tool_choice="auto",
                temperature=0.0,
            )
        except Exception as exc:
            error_msg = (
                "I'm sorry, I encountered an error communicating with the "
                f"AI service. Please try again. (Error: {exc})"
            )
            return _build_response(session_id, session, error_msg)

        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []

        # -- No tool calls: extract text and finish -------------------------
        if not tool_calls:
            final_text = msg.content or ""
            memory.add_assistant_message(session_id, final_text)
            break

        # -- Has tool calls: store message and execute tools ----------------
        tc_list = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]
        memory.add_assistant_message(session_id, msg.content, tc_list)

        tool_results = []
        for tc in tool_calls:
            tool_call_count += 1
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}

            tool_calls_this_turn.append(name)
            audit_log.log_tool_called(trace_id, session_id, name, list(args.keys()))

            if name == "book_appointment":
                audit_log.log_booking_attempt(
                    trace_id, session_id,
                    patient_id=args.get("patient_id", "unknown"),
                    slot_id=str(args.get("slot_id", "")),
                    appointment_type=str(args.get("appointment_type", "")),
                )

            allowed, reason = _check_tool_allowed(name, session)
            if not allowed:
                result = {"error": f"Action not allowed: {reason}"}
            else:
                result_str = tool_executor.run(name, args, db, session)
                _log_tool_call(name, args, result_str)
                _update_state(name, result_str, session, sessions)
                try:
                    result = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    result = {"result": str(result_str)}

                if name == "book_appointment" and isinstance(result, dict):
                    last_confirmed_booking = result.get("confirmation_number")

                result = _phi_strip_for_llm(name, result)

            if not isinstance(result, dict):
                result = {"data": result}

            tool_results.append({
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

        memory.add_tool_results(session_id, tool_results)
        continue

    if tool_call_count >= MAX_TOOL_CALLS:
        final_text = (
            "I've reached the maximum number of lookups for this turn. "
            "Please try rephrasing or continue with the next step."
        )

    # 5. Output guardrail
    output_flag = check_output(final_text)
    if not output_flag.is_clean:
        audit_log.log_output_flagged(trace_id, session_id, output_flag.flags)
        final_text = sanitize_output(final_text, output_flag)

    # 6. Booking cross-check
    if not verify_booking_in_response(final_text, last_confirmed_booking):
        audit_log.log_output_flagged(trace_id, session_id, ["booking_confirmation_mismatch"])
        import re
        final_text = re.sub(r"\bCCA-[0-9A-F]{8}\b", "[CONFIRMATION PENDING]", final_text)

    audit_log.log_response_sent(trace_id, session_id, len(final_text))
    return _build_response(session_id, session, final_text, tool_calls_this_turn)


# ---------------------------------------------------------------------------
# PHI minimisation
# ---------------------------------------------------------------------------

_PHI_STRIP_MAP: dict[str, set] = {
    "verify_patient": {"dob"},
    "book_appointment": {"patient_id"},
    "get_booking_history": {"patient_id"},
}


def _phi_strip_for_llm(tool_name: str, result: dict) -> dict:
    strip_keys = _PHI_STRIP_MAP.get(tool_name, set())
    if not strip_keys:
        return result
    return {k: v for k, v in result.items() if k not in strip_keys}


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def _check_tool_allowed(tool_name: str, session: dict) -> tuple:
    patient_specific = {
        "get_booking_history", "find_available_slots",
        "book_appointment", "check_provider_availability",
    }
    if tool_name in patient_specific and not session.get("patient_confirmed"):
        return False, "Please verify the patient's identity first using verify_patient."
    return True, ""


# ---------------------------------------------------------------------------
# Workflow state updates
# ---------------------------------------------------------------------------

def _update_state(
    tool_name: str, result_str: str, session: dict, sessions: dict,
) -> None:
    try:
        result = json.loads(result_str)
    except Exception:
        return

    state = session.get("state")

    if tool_name == "verify_patient" and result.get("found"):
        if state == WorkflowState.GREET:
            transition_to(session, WorkflowState.VERIFY_PATIENT)
        transition_to(session, WorkflowState.COLLECT_REFERRAL)
        if not session.get("referrals"):
            add_referral(session)

    elif tool_name == "find_available_slots" and result.get("slots"):
        if state in (
            WorkflowState.COLLECT_REFERRAL,
            WorkflowState.DETERMINE_APPT_TYPE,
        ):
            transition_to(session, WorkflowState.CHECK_AVAILABILITY)

    elif tool_name == "verify_insurance":
        if state == WorkflowState.CHECK_AVAILABILITY:
            transition_to(session, WorkflowState.VERIFY_INSURANCE)

    elif tool_name == "book_appointment" and result.get("success"):
        transition_to(session, WorkflowState.BOOKING_CONFIRMED)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_tool_call(name: str, inp: dict, result: str) -> None:
    try:
        r = json.loads(result)
        if "error" in r:
            summary = f"ERROR: {r['error']}"
        elif "found" in r and not r["found"]:
            summary = r.get("message", "not found")
        elif "confirmation_number" in r:
            summary = f"booked → {r['confirmation_number']}"
        elif "name" in r:
            summary = str(r["name"])
        elif isinstance(r, list) and r:
            summary = f"{len(r)} results"
        else:
            summary = "ok"
    except Exception:
        summary = result[:80]

    inp_str = ", ".join(f'{k}="{v}"' for k, v in inp.items())
    print(f"  → {name}({inp_str})")
    print(f"  ← {summary}")


def _build_response(
    session_id: str,
    session: dict,
    text: str,
    tool_calls: Optional[list] = None,
) -> dict:
    state = session.get("state", WorkflowState.GREET)
    return {
        "session_id": session_id,
        "response": text,
        "workflow_state": state.value if hasattr(state, "value") else str(state),
        "action_cards": [],
        "requires_confirmation": state == WorkflowState.CONFIRM_BOOKING,
        "tool_calls": tool_calls or [],
    }
