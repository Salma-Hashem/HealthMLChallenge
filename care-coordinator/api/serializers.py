"""
Serialization helpers for the Care Coordinator API.

Converts internal Pydantic models and session dicts to plain JSON-serializable
dicts for HTTP responses.  Used by all route blueprints.
"""


def serialize_patient(patient) -> dict:
    return {
        "id": patient.id,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "dob": patient.dob.isoformat(),
        "pcp": patient.pcp,
        "ehr_id": patient.ehr_id,
        "referred_providers": [
            {
                "specialty": r.specialty,
                "provider_name": r.provider_name,
                "provider_id": r.provider_id,
            }
            for r in patient.referred_providers
        ],
        "insurance": patient.insurance,
    }


def serialize_provider(provider, include_hours=False) -> dict:
    departments = []
    for d in provider.departments:
        dept: dict = {
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "address": d.address,
        }
        if include_hours:
            dept["hours"] = [oh.model_dump() for oh in d.hours]
        departments.append(dept)

    return {
        "id": provider.id,
        "first_name": provider.first_name,
        "last_name": provider.last_name,
        "certification": provider.certification,
        "specialty": provider.specialty,
        "departments": departments,
    }


def serialize_slot(slot) -> dict:
    return {
        "id": slot.id,
        "provider_id": slot.provider_id,
        "department_id": slot.department_id,
        "start": slot.start.isoformat(),
        "end": slot.end.isoformat(),
        "duration_minutes": slot.duration_minutes,
        "is_available": slot.is_available,
    }
