"""
PHI field policy for the Care Coordinator Assistant.

Single source of truth for which fields must be stripped from tool results
before they enter LLM message history or are exposed in responses.

To add a new PHI field: update PHI_STRIP_MAP here only.
agent/graph.py and agent/orchestrator.py both import from this module.
"""

PHI_STRIP_MAP: dict[str, set[str]] = {
    "verify_patient":      {"dob"},
    "book_appointment":    {"patient_id"},
    "get_booking_history": {"patient_id"},
}
