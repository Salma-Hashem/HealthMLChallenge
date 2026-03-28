"""
Conversation memory manager for the Care Coordinator Assistant.

Stores per-session message history in OpenAI messages format with a rolling
window and automatic session expiry.

Internal format per message (OpenAI-compatible):
    {"role": "user",      "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [...]}   # optional tool_calls
    {"role": "tool",      "tool_call_id": "...", "content": "..."}
"""

import time
from typing import List, Optional

_store: dict = {}

MAX_MESSAGES = 80       # higher limit to account for tool result messages
SESSION_TTL = 8 * 3600  # 8 hours of inactivity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_user_message(session_id: str, content: str) -> None:
    """Append a plain-text user message."""
    _get(session_id)["messages"].append({"role": "user", "content": content})
    _touch(session_id)
    _trim(session_id)


def add_assistant_message(
    session_id: str,
    content: Optional[str],
    tool_calls: Optional[list] = None,
) -> None:
    """Append an assistant message, optionally with tool_calls.

    tool_calls is a list of OpenAI-format tool call dicts:
        [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}]
    """
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    _get(session_id)["messages"].append(msg)
    _touch(session_id)
    _trim(session_id)


def add_tool_results(session_id: str, results: List[dict]) -> None:
    """Append one tool-result message per result.

    Each result dict:
        {"tool_call_id": "...", "content": "..."}  # content is a JSON string
    """
    store = _get(session_id)
    for r in results:
        store["messages"].append({
            "role": "tool",
            "tool_call_id": r["tool_call_id"],
            "content": r["content"],
        })
    _touch(session_id)
    _trim(session_id)


def get_messages(session_id: str) -> List[dict]:
    """Return a copy of the message history for this session."""
    _cleanup_expired()
    if session_id not in _store:
        return []
    return list(_store[session_id]["messages"])


def pop_last_assistant_turn(session_id: str) -> None:
    """Remove the last assistant turn to support response regeneration.

    Walks backward through:
    1. The last assistant text-only message (no tool_calls)
    2. Any tool result messages (role=tool)
    3. The assistant message that triggered those tool calls
    Repeats until it reaches the plain user message being re-processed.
    """
    if session_id not in _store:
        return
    msgs = _store[session_id]["messages"]

    # Pop the last plain assistant text response
    if msgs and msgs[-1]["role"] == "assistant" and not msgs[-1].get("tool_calls"):
        msgs.pop()

    # Pop interleaved tool-result / assistant-tool-call pairs
    while msgs:
        if msgs[-1]["role"] == "tool":
            msgs.pop()
        elif msgs[-1]["role"] == "assistant" and msgs[-1].get("tool_calls"):
            msgs.pop()
        else:
            break


def clear(session_id: str) -> None:
    """Wipe a session's history."""
    _store.pop(session_id, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(session_id: str) -> dict:
    if session_id not in _store:
        _store[session_id] = {"messages": [], "last_active": time.time()}
    return _store[session_id]


def _touch(session_id: str) -> None:
    if session_id in _store:
        _store[session_id]["last_active"] = time.time()


def _trim(session_id: str) -> None:
    """Keep only the most recent MAX_MESSAGES messages."""
    msgs = _store[session_id]["messages"]
    if len(msgs) > MAX_MESSAGES:
        _store[session_id]["messages"] = msgs[-MAX_MESSAGES:]


def _cleanup_expired() -> None:
    now = time.time()
    expired = [sid for sid, s in _store.items()
               if now - s["last_active"] > SESSION_TTL]
    for sid in expired:
        del _store[sid]
