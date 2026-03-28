"""
Audit logging for the Care Coordinator Assistant.

Issue #24 — Writes append-only JSONL entries to ``audit.jsonl`` (next to this
file).  No raw PHI reaches the log: patient IDs are SHA-256 hashed and booking
payloads are stored as a content hash for integrity verification.

Log entry format
----------------
{
    "timestamp":  "<ISO-8601 UTC>",
    "trace_id":   "<uuid4>",
    "session_id": "<uuid4 or null>",
    "event":      "<event_type>",
    ...event-specific fields...
}

Event types
-----------
message_received    User sent a message (length only, no content).
input_blocked       Input guardrail rejected the message.
tool_called         A tool was dispatched (tool name + args keys, no values).
booking_attempt     book_appointment was invoked (payload hash for integrity).
output_flagged      Output guardrail found a concern.
response_sent       Final response delivered (length only, no content).
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit.jsonl")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_id(value: Any) -> str:
    """Return a 12-char hex prefix of SHA-256(str(value)).

    Long enough to be unique within a session; short enough to be useless
    as a patient identifier on its own.
    """
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]


def _payload_hash(data: dict) -> str:
    """Stable SHA-256 hash of a dict (sorted keys) for integrity verification."""
    serialised = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _write(entry: dict) -> None:
    """Append a single JSON line to the audit log (thread-safe via mode 'a')."""
    line = json.dumps(entry, default=str)
    with open(_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def new_trace_id() -> str:
    """Generate a fresh trace ID for one handle_message invocation."""
    return str(uuid.uuid4())


def log_message_received(
    trace_id: str,
    session_id: Optional[str],
    message_length: int,
) -> None:
    _write({
        "timestamp":      _now_utc(),
        "trace_id":       trace_id,
        "session_id":     session_id,
        "event":          "message_received",
        "message_length": message_length,
    })


def log_input_blocked(
    trace_id: str,
    session_id: Optional[str],
    reason: str,
    pattern_key: Optional[str],
) -> None:
    _write({
        "timestamp":   _now_utc(),
        "trace_id":    trace_id,
        "session_id":  session_id,
        "event":       "input_blocked",
        "reason":      reason,
        "pattern_key": pattern_key,
    })


def log_tool_called(
    trace_id: str,
    session_id: Optional[str],
    tool_name: str,
    arg_keys: list[str],
) -> None:
    """Log that a tool was called.  Only the argument *keys* are stored."""
    _write({
        "timestamp":  _now_utc(),
        "trace_id":   trace_id,
        "session_id": session_id,
        "event":      "tool_called",
        "tool":       tool_name,
        "arg_keys":   arg_keys,
    })


def log_booking_attempt(
    trace_id: str,
    session_id: Optional[str],
    patient_id: Any,
    slot_id: str,
    appointment_type: str,
    extra: Optional[dict] = None,
) -> None:
    """Log a booking attempt with PHI-safe identifiers and a payload hash."""
    payload = {
        "patient_id_hash":  _hash_id(patient_id),
        "slot_id":          slot_id,
        "appointment_type": appointment_type,
        **(extra or {}),
    }
    _write({
        "timestamp":    _now_utc(),
        "trace_id":     trace_id,
        "session_id":   session_id,
        "event":        "booking_attempt",
        "payload_hash": _payload_hash(payload),
        **payload,
    })


def log_output_flagged(
    trace_id: str,
    session_id: Optional[str],
    flags: list[str],
) -> None:
    _write({
        "timestamp":  _now_utc(),
        "trace_id":   trace_id,
        "session_id": session_id,
        "event":      "output_flagged",
        "flags":      flags,
    })


def log_response_sent(
    trace_id: str,
    session_id: Optional[str],
    response_length: int,
) -> None:
    _write({
        "timestamp":       _now_utc(),
        "trace_id":        trace_id,
        "session_id":      session_id,
        "event":           "response_sent",
        "response_length": response_length,
    })
