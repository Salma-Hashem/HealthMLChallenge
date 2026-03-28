"""
Policy engine for the Care Coordinator Assistant.

Contains deterministic business rule functions for appointment type
determination, duration calculation, arrival instructions, office hours
validation, and full booking request validation.
"""

from datetime import date, datetime
from typing import Dict, List, Optional

from models import OfficeHours


def determine_appointment_type(last_seen_date: Optional[date]) -> str:
    """Return 'NEW' if never seen or >5 years ago, else 'ESTABLISHED'."""
    if last_seen_date is None:
        return "NEW"
    years_since = (date.today() - last_seen_date).days / 365.25
    if years_since > 5:
        return "NEW"
    return "ESTABLISHED"


def get_appointment_duration(appointment_type: str) -> int:
    """Return 30 for NEW, 15 for ESTABLISHED."""
    return 30 if appointment_type == "NEW" else 15


def get_arrival_instructions(appointment_type: str) -> str:
    """Return arrival-time guidance based on appointment type."""
    if appointment_type == "NEW":
        return "Please arrive 30 minutes before your appointment."
    return "Please arrive 10 minutes before your appointment."


def validate_slot_within_office_hours(
    slot_start: datetime,
    slot_end: datetime,
    department_hours: List[OfficeHours],
) -> bool:
    """Check that the proposed slot falls within the department's office hours."""
    slot_day = slot_start.weekday()
    for oh in department_hours:
        if oh.day_of_week == slot_day:
            day_open = datetime.combine(slot_start.date(), oh.open_time)
            day_close = datetime.combine(slot_start.date(), oh.close_time)
            if slot_start >= day_open and slot_end <= day_close:
                return True
    return False


def get_last_seen_date(
    patient_id: int,
    provider_id: int,
    appointments: list,
) -> Optional[date]:
    """Return the most recent *completed* appointment date, or None."""
    last: Optional[date] = None
    for appt in appointments:
        if (
            appt.patient_id == patient_id
            and appt.provider_id == provider_id
            and appt.status == "completed"
        ):
            if last is None or appt.date > last:
                last = appt.date
    return last


def validate_booking_request(
    patient_id: int,
    slot_id: str,
    appointment_type: str,
    slots_db: dict,
    patients_db: dict,
    appointments_db: list,
    departments_db: dict,
    providers_db: dict,
) -> dict:
    """Run ALL validations before booking.

    1. Patient exists
    2. Slot exists and is available
    3. Slot is within office hours
    4. Appointment type is correct (re-derived from history)
    5. Slot duration is sufficient

    Returns {"valid": bool, "errors": [...], "warnings": [...], "corrected_type": str}
    """
    errors: List[str] = []
    warnings: List[str] = []
    corrected_type = appointment_type

    if patient_id not in patients_db:
        errors.append(f"Patient {patient_id} not found")

    slot = slots_db.get(slot_id)
    if slot is None:
        errors.append(f"Slot {slot_id} not found")
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "corrected_type": corrected_type,
        }

    if not slot.is_available:
        errors.append(f"Slot {slot_id} is not available")

    dept = departments_db.get(slot.department_id)
    if dept is not None:
        if not validate_slot_within_office_hours(slot.start, slot.end, dept.hours):
            errors.append("Slot is outside office hours")

    last_seen = get_last_seen_date(patient_id, slot.provider_id, appointments_db)
    corrected_type = determine_appointment_type(last_seen)

    if corrected_type != appointment_type:
        warnings.append(
            f"Appointment type corrected from {appointment_type} to "
            f"{corrected_type} based on patient history"
        )

    required_duration = get_appointment_duration(corrected_type)
    if slot.duration_minutes < required_duration:
        errors.append(
            f"Slot duration ({slot.duration_minutes}min) is less than "
            f"required {required_duration}min for {corrected_type} appointment"
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "corrected_type": corrected_type,
    }
