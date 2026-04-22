"""
Workflow state definitions for the Care Coordinator Assistant.

WorkflowState is the vocabulary the LangGraph agent uses to label the current
stage of a booking conversation.  The graph reads and writes the string value
(e.g. "collect_referral") in CareState; this enum provides a typed reference
for the rest of the codebase.

State transitions are driven by the LangGraph graph in agent/graph.py, not by
this module.
"""

from enum import Enum


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
