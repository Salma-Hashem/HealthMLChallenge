"""
Tool: list_alternative_providers

Finds other providers in the same specialty when the preferred provider
is unavailable. Optionally enriches each result with patient history
and next available slots for instant "No, but..." routing.
"""

from datetime import date, datetime, timedelta

from core.policy import determine_appointment_type, get_last_seen_date
from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import ListAlternativeProvidersArgs, schema_for


class ListAlternativeProvidersTool(BaseTool):
    name = "list_alternative_providers"
    description = (
        "Find other providers in the same specialty when the preferred provider "
        "is unavailable or has no open slots at the requested time. "
        "Pass patient_id and duration to get next available slots and patient history "
        "(e.g. 'patient saw Dr. Jones in 2022') for each alternative — "
        "use this to give the nurse instant 'No, but...' alternatives."
    )
    schema = schema_for(ListAlternativeProvidersArgs)
    requires_patient_verification = False

    def execute(self, args: dict, db: dict, session: dict):
        specialty = args["specialty"].strip()
        exclude_id = int(args["exclude_provider_id"]) if args.get("exclude_provider_id") is not None else None
        patient_id = int(args["patient_id"]) if args.get("patient_id") is not None else None
        duration = int(args["duration"]) if args.get("duration") is not None else None

        today = date.today()
        date_from = datetime.combine(today, datetime.min.time())
        date_to = datetime.combine(
            today + timedelta(days=28),
            datetime.max.time().replace(microsecond=0),
        )

        matches = []
        for p in db["providers"].values():
            if p.specialty.lower() != specialty.lower():
                continue
            if exclude_id is not None and p.id == exclude_id:
                continue

            depts = [
                {
                    "location_id": d.id,
                    "name": d.name,
                    "address": d.address,
                    "phone": d.phone,
                }
                for d in p.departments
            ]
            entry: dict = {
                "provider_id": p.id,
                "name": p.display_name,
                "specialty": p.specialty,
                "departments": depts,
            }

            # Patient history context
            if patient_id is not None:
                last_seen = get_last_seen_date(patient_id, p.id, db["appointments"])
                appt_type = determine_appointment_type(last_seen)
                entry["patient_history"] = {
                    "last_seen_date": last_seen.isoformat() if last_seen else None,
                    "appointment_type": appt_type,
                }

            # Next available slots — use pre-built index for O(1) provider lookup
            candidate_slots = db.get("slots_by_provider", {}).get(p.id) or [
                s for s in db["slots"].values() if s.provider_id == p.id
            ]
            provider_slots = sorted(
                [
                    s for s in candidate_slots
                    if s.is_available
                    and (duration is None or s.duration_minutes == duration)
                    and date_from <= s.start <= date_to
                ],
                key=lambda s: s.start,
            )
            entry["next_available_slots"] = [
                {
                    "slot_id": s.id,
                    "date": s.start.strftime("%A, %B %d, %Y"),
                    "time": s.start.strftime("%I:%M %p"),
                    "duration_minutes": s.duration_minutes,
                    "location": db["departments"].get(s.department_id).name
                    if db["departments"].get(s.department_id) else "Unknown",
                    "address": db["departments"].get(s.department_id).address
                    if db["departments"].get(s.department_id) else "",
                }
                for s in provider_slots[:3]
            ]

            matches.append(entry)

        if not matches:
            return {
                "found": False,
                "message": f"No alternative providers found for specialty: {specialty}",
            }
        return {"found": True, "alternatives": matches}


registry.register(ListAlternativeProvidersTool())
