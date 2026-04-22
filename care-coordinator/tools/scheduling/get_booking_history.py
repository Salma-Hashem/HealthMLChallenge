"""
Tool: get_booking_history

Checks whether a patient has seen a specific provider before and returns
the correct appointment type (NEW or ESTABLISHED) with required duration.
"""

from core.policy import (
    determine_appointment_type,
    get_appointment_duration,
    get_arrival_instructions,
    get_last_seen_date,
)
from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import GetBookingHistoryArgs, schema_for


class GetBookingHistoryTool(BaseTool):
    name = "get_booking_history"
    description = (
        "Check whether a patient has seen a specific provider before and determine "
        "the correct appointment type (NEW or ESTABLISHED). "
        "ALWAYS call this before searching for slots — it tells you the required duration."
    )
    schema = schema_for(GetBookingHistoryArgs)
    requires_patient_verification = True

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        patient_id = int(args["patient_id"])
        provider_id = int(args["provider_id"])

        last_seen = get_last_seen_date(patient_id, provider_id, db["appointments"])
        appt_type = determine_appointment_type(last_seen)
        duration = get_appointment_duration(appt_type)
        arrival = get_arrival_instructions(appt_type)

        return {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "last_seen_date": last_seen.isoformat() if last_seen else None,
            "appointment_type": appt_type,
            "required_duration_minutes": duration,
            "arrival_instructions": arrival,
        }


registry.register(GetBookingHistoryTool())
