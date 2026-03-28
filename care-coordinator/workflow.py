"""
Workflow state machine for the Care Coordinator Assistant.

Manages per-session conversation state through the appointment booking flow:
GREET → VERIFY_PATIENT → COLLECT_REFERRAL → DETERMINE_APPT_TYPE →
CHECK_AVAILABILITY → SUGGEST_ALTERNATIVES → VERIFY_INSURANCE →
CONFIRM_BOOKING → EXECUTE_BOOKING → BOOKING_CONFIRMED → FINAL_SUMMARY
"""

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional
import uuid


class WorkflowState(Enum):
    GREET = "greet"
    VERIFY_PATIENT = "verify_patient"
    COLLECT_REFERRAL = "collect_referral"
    DETERMINE_APPT_TYPE = "determine_appt_type"
    CHECK_AVAILABILITY = "check_availability"
    SUGGEST_ALTERNATIVES = "suggest_alternatives"
    VERIFY_INSURANCE = "verify_insurance"
    CONFIRM_BOOKING = "confirm_booking"
    EXECUTE_BOOKING = "execute_booking"
    BOOKING_CONFIRMED = "booking_confirmed"
    FINAL_SUMMARY = "final_summary"


DEFAULT_TRANSITIONS = [
    WorkflowState.GREET,
    WorkflowState.VERIFY_PATIENT,
    WorkflowState.COLLECT_REFERRAL,
    WorkflowState.DETERMINE_APPT_TYPE,
    WorkflowState.CHECK_AVAILABILITY,
    WorkflowState.VERIFY_INSURANCE,
    WorkflowState.CONFIRM_BOOKING,
    WorkflowState.EXECUTE_BOOKING,
    WorkflowState.BOOKING_CONFIRMED,
    WorkflowState.FINAL_SUMMARY,
]


def create_session() -> dict:
    """Create a new conversation session in the GREET state."""
    return {
        "session_id": str(uuid.uuid4()),
        "state": WorkflowState.GREET,
        "patient_id": None,
        "patient_confirmed": False,
        "referrals": [],
        "active_referral_index": 0,
        "completed_bookings": [],
        "created_at": datetime.utcnow().isoformat(),
    }


def _active_referral(session: dict) -> Optional[dict]:
    idx = session["active_referral_index"]
    if 0 <= idx < len(session["referrals"]):
        return session["referrals"][idx]
    return None


def get_required_fields(state: WorkflowState) -> Dict[str, str]:
    """Return a mapping of field → description of what the current state needs."""
    return {
        WorkflowState.GREET: {},
        WorkflowState.VERIFY_PATIENT: {
            "patient_id": "Patient must be identified",
            "patient_confirmed": "Patient identity must be confirmed",
        },
        WorkflowState.COLLECT_REFERRAL: {
            "referral.specialty": "Referral specialty required",
            "referral.provider_id": "Provider must be selected",
            "referral.location_id": "Location must be selected",
        },
        WorkflowState.DETERMINE_APPT_TYPE: {
            "referral.appointment_type": "Appointment type must be determined",
        },
        WorkflowState.CHECK_AVAILABILITY: {
            "referral.slot_id": "A time slot must be selected",
        },
        WorkflowState.SUGGEST_ALTERNATIVES: {
            "referral.provider_id": "Alternative provider must be selected",
            "referral.slot_id": "A time slot must be selected",
        },
        WorkflowState.VERIFY_INSURANCE: {
            "referral.insurance_verified": "Insurance must be verified",
        },
        WorkflowState.CONFIRM_BOOKING: {
            "confirmation": "Nurse must confirm the booking",
        },
        WorkflowState.EXECUTE_BOOKING: {
            "referral.booked": "Booking must be executed",
        },
        WorkflowState.BOOKING_CONFIRMED: {},
        WorkflowState.FINAL_SUMMARY: {},
    }.get(state, {})


def can_advance(session: dict) -> bool:
    """Return True if the current state's requirements are satisfied."""
    state = session["state"]
    ref = _active_referral(session)

    if state == WorkflowState.GREET:
        return True

    if state == WorkflowState.VERIFY_PATIENT:
        return (
            session.get("patient_id") is not None
            and session.get("patient_confirmed") is True
        )

    if state == WorkflowState.COLLECT_REFERRAL:
        if ref is None:
            return False
        return bool(
            ref.get("specialty")
            and ref.get("provider_id") is not None
            and ref.get("location_id") is not None
        )

    if state == WorkflowState.DETERMINE_APPT_TYPE:
        return ref is not None and ref.get("appointment_type") is not None

    if state in (WorkflowState.CHECK_AVAILABILITY, WorkflowState.SUGGEST_ALTERNATIVES):
        return ref is not None and ref.get("slot_id") is not None

    if state == WorkflowState.VERIFY_INSURANCE:
        return ref is not None and ref.get("insurance_verified") is True

    if state == WorkflowState.CONFIRM_BOOKING:
        return True

    if state == WorkflowState.EXECUTE_BOOKING:
        return ref is not None and ref.get("booked") is True

    if state in (WorkflowState.BOOKING_CONFIRMED, WorkflowState.FINAL_SUMMARY):
        return True

    return False


def advance(session: dict) -> dict:
    """Move to the next state along the default linear path.

    Raises ValueError if the current state's requirements are not met.
    """
    if not can_advance(session):
        state = session["state"]
        missing = get_required_fields(state)
        raise ValueError(
            f"Cannot advance from {state.value}. "
            f"Missing: {list(missing.keys())}"
        )

    state = session["state"]
    if state in DEFAULT_TRANSITIONS:
        idx = DEFAULT_TRANSITIONS.index(state)
        if idx + 1 < len(DEFAULT_TRANSITIONS):
            session["state"] = DEFAULT_TRANSITIONS[idx + 1]
            return session

    raise ValueError(f"No default transition from {state.value}")


def transition_to(session: dict, target_state: WorkflowState) -> dict:
    """Force-transition to a specific state (for branching paths)."""
    session["state"] = target_state
    return session


def add_referral(session: dict) -> dict:
    """Append a blank referral and make it the active one."""
    referral = {
        "specialty": None,
        "provider_id": None,
        "location_id": None,
        "appointment_type": None,
        "slot_id": None,
        "insurance_verified": False,
        "booked": False,
        "confirmation_number": None,
    }
    session["referrals"].append(referral)
    session["active_referral_index"] = len(session["referrals"]) - 1
    return session


def get_session_summary(session: dict) -> dict:
    """Produce an itinerary of all completed bookings in this session."""
    bookings = []
    for ref in session["referrals"]:
        if ref.get("booked"):
            bookings.append({
                "specialty": ref["specialty"],
                "provider_id": ref["provider_id"],
                "location_id": ref["location_id"],
                "appointment_type": ref["appointment_type"],
                "slot_id": ref["slot_id"],
                "confirmation_number": ref["confirmation_number"],
            })
    return {
        "session_id": session["session_id"],
        "patient_id": session["patient_id"],
        "total_referrals": len(session["referrals"]),
        "completed_bookings": bookings,
    }
