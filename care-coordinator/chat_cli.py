"""
CLI chat interface for the Care Coordinator Assistant (Issue #14).

Interactive terminal session for testing the full LLM + tool + booking flow.

Usage:
    python chat_cli.py

Commands during chat:
    quit / exit  — end the session
    state        — show current workflow state and session details
    reset        — start a brand-new session
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Add the project root to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import load_all_data
from slot_generator import generate_slots
from orchestrator import handle_message
from workflow import WorkflowState

# ── ANSI colours ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
GREY   = "\033[90m"
RED    = "\033[31m"
BLUE   = "\033[34m"


def colour(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


# ── Bootstrap data ────────────────────────────────────────────────────────────

DATA_SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_sheet.txt")

def load_db() -> dict:
    db = load_all_data(DATA_SHEET)
    db["slots"] = generate_slots(db["providers"], db["departments"])
    return db


# ── Session display ───────────────────────────────────────────────────────────

def print_state(session: dict) -> None:
    state = session.get("state", WorkflowState.GREET)
    state_name = state.value if hasattr(state, "value") else str(state)
    patient_id = session.get("patient_id")
    confirmed = session.get("patient_confirmed", False)
    referrals = session.get("referrals", [])

    print(colour(f"\n{'─'*50}", GREY))
    print(colour(f"  State       : {state_name.upper()}", CYAN))
    print(colour(f"  Patient ID  : {patient_id or 'not verified'}", CYAN))
    print(colour(f"  Confirmed   : {'yes' if confirmed else 'no'}", CYAN))
    print(colour(f"  Referrals   : {len(referrals)} ({sum(1 for r in referrals if r.get('booked'))} booked)", CYAN))
    for i, ref in enumerate(referrals):
        status = colour("✓ booked", GREEN) if ref.get("booked") else colour("pending", YELLOW)
        conf = f" — {ref['confirmation_number']}" if ref.get("confirmation_number") else ""
        print(colour(f"    [{i}] {ref.get('specialty', '?')} — {status}{conf}", GREY))
    print(colour(f"{'─'*50}\n", GREY))


def print_banner() -> None:
    print(colour("\n╔══════════════════════════════════════════════╗", CYAN))
    print(colour("║   Care Coordinator Assistant — CLI Chat     ║", CYAN))
    print(colour("╠══════════════════════════════════════════════╣", CYAN))
    print(colour("║  Commands: quit · exit · state · reset      ║", GREY))
    print(colour("╚══════════════════════════════════════════════╝\n", CYAN))


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    print_banner()

    db = load_db()
    sessions: dict = {}
    session_id: str | None = None

    print(colour("Type your message to begin. The assistant will greet you on your first message.\n", GREY))

    while True:
        try:
            user_input = input(colour("You: ", BOLD + GREEN)).strip()
        except (EOFError, KeyboardInterrupt):
            print(colour("\n\nSession ended.", GREY))
            break

        if not user_input:
            continue

        # ── Built-in commands ──────────────────────────────────────────
        if user_input.lower() in ("quit", "exit"):
            print(colour("\nGoodbye!", CYAN))
            break

        if user_input.lower() == "reset":
            session_id = None
            sessions.clear()
            db = load_db()          # fresh data so booked slots reset too
            print(colour("\n[Session reset. Starting fresh.]\n", YELLOW))
            continue

        if user_input.lower() == "state":
            if session_id and session_id in sessions:
                print_state(sessions[session_id])
            else:
                print(colour("  No active session yet.\n", GREY))
            continue

        # ── Send message to orchestrator ───────────────────────────────
        state_label = ""
        if session_id and session_id in sessions:
            s = sessions[session_id].get("state", WorkflowState.GREET)
            state_label = f" [{s.value.upper()}]" if hasattr(s, "value") else ""

        print(colour(f"\nAssistant{state_label}:", BOLD + BLUE))

        try:
            result = handle_message(session_id, user_input, db, sessions)
        except Exception as exc:
            print(colour(f"  ERROR: {exc}\n", RED))
            continue

        session_id = result["session_id"]
        response_text = result.get("response", "")
        new_state = result.get("workflow_state", "")
        requires_confirm = result.get("requires_confirmation", False)

        # Print assistant response
        print(f"{response_text}\n")

        # Print workflow state badge
        badge = colour(f"[{new_state.upper()}]", YELLOW)
        if requires_confirm:
            badge += colour(" ⚠ Awaiting confirmation", RED)
        print(colour(f"  {badge}", GREY))
        print()


if __name__ == "__main__":
    main()
