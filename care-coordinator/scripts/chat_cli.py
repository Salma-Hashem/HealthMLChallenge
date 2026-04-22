"""
CLI chat interface for the Care Coordinator Assistant.

Interactive terminal session for testing the full LLM + tool + booking flow.

Usage:
    python scripts/chat_cli.py

Commands during chat:
    quit / exit  — end the session
    state        — show current workflow state and session details
    reset        — start a brand-new session
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Add the project root to path so all packages are importable.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from data.loader import load_all_data
from core.slots import generate_slots
from agent.orchestrator import handle_message
from agent.graph import make_graph
import agent.orchestrator as _orchestrator

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

_DATA_SHEET = os.path.join(_PROJECT_ROOT, "data", "data_sheet.txt")


def load_db() -> dict:
    db = load_all_data(_DATA_SHEET)
    db["slots"] = generate_slots(db["providers"], db["departments"])
    _orchestrator.set_graph(make_graph(db))
    return db



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
            db = load_db()          # fresh data so booked slots reset too
            print(colour("\n[Session reset. Starting fresh.]\n", YELLOW))
            continue

        if user_input.lower() == "state":
            print(colour("  No active session yet.\n", GREY))
            continue

        # ── Send message to orchestrator ───────────────────────────────
        print(colour(f"\nAssistant:", BOLD + BLUE))

        try:
            result = handle_message(session_id, user_input, db)
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
