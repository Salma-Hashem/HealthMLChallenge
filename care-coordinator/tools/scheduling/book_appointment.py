"""
Tool: book_appointment

Finalises an appointment booking after explicit nurse confirmation.
Marks the slot as taken, creates an Appointment record, issues a
confirmation number, and advances the session referral state.
"""

import uuid
from typing import Optional

from core.models import Appointment
from core.policy import get_arrival_instructions, validate_booking_request
from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import BookAppointmentArgs, schema_for


def _active_referral(session: dict) -> Optional[dict]:
    idx = session.get("active_referral_index", 0)
    refs = session.get("referrals", [])
    return refs[idx] if 0 <= idx < len(refs) else None


class BookAppointmentTool(BaseTool):
    name = "book_appointment"
    description = (
        "FINALIZE an appointment booking after the nurse has explicitly confirmed. "
        "ONLY call this after the nurse says 'yes', 'confirm', 'book it', or similar. "
        "This action is irreversible — it marks the slot as taken and issues a confirmation number."
    )
    schema = schema_for(BookAppointmentArgs)
    requires_patient_verification = True

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        patient_id = int(args["patient_id"])
        slot_id = str(args["slot_id"])
        appt_type = str(args.get("appointment_type", "NEW"))
        reason = str(args.get("reason", ""))

        validation = validate_booking_request(
            patient_id, slot_id, appt_type,
            db["slots"], db["patients"], db["appointments"],
            db["departments"], db["providers"],
        )

        if not validation["valid"]:
            return {"success": False, "errors": validation["errors"]}

        slot = db["slots"][slot_id]
        slot.is_available = False
        corrected_type = validation["corrected_type"]

        confirmation = f"CCA-{uuid.uuid4().hex[:8].upper()}"
        next_id = max((a.id for a in db["appointments"]), default=0) + 1

        appointment = Appointment(
            id=next_id,
            patient_id=patient_id,
            provider_id=slot.provider_id,
            date=slot.start.date(),
            time=slot.start.time(),
            status="booked",
            confirmation_number=confirmation,
            appointment_type=corrected_type,
            reason=reason,
        )
        db["appointments"].append(appointment)

        provider = db["providers"].get(slot.provider_id)
        dept = db["departments"].get(slot.department_id)

        # Advance session referral state
        ref = _active_referral(session)
        if ref is not None:
            ref["booked"] = True
            ref["confirmation_number"] = confirmation
            ref["appointment_type"] = corrected_type
            ref["slot_id"] = slot_id

        return {
            "success": True,
            "confirmation_number": confirmation,
            "patient_id": patient_id,
            "provider": provider.display_name if provider else "Unknown",
            "department": dept.name if dept else "Unknown",
            "address": dept.address if dept else "",
            "phone": dept.phone if dept else "",
            "date": slot.start.strftime("%A, %B %d, %Y"),
            "time": slot.start.strftime("%I:%M %p"),
            "duration_minutes": slot.duration_minutes,
            "appointment_type": corrected_type,
            "arrival_instructions": get_arrival_instructions(corrected_type),
            "warnings": validation.get("warnings", []),
        }


registry.register(BookAppointmentTool())
