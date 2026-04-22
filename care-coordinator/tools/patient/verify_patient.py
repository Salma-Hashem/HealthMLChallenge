"""
Tool: verify_patient

Searches for a patient by name and/or date of birth, confirms their
identity, and seeds the session so downstream tools can run.
"""

from datetime import date

from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import VerifyPatientArgs, schema_for


class VerifyPatientTool(BaseTool):
    name = "verify_patient"
    description = (
        "Search for a patient by name and/or date of birth to verify their identity. "
        "ALWAYS call this first — before any patient-specific action. "
        "On success, updates the session so patient-specific tools become available."
    )
    schema = schema_for(VerifyPatientArgs)
    requires_patient_verification = False

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        first = args.get("first_name", "").strip().lower()
        last = args.get("last_name", "").strip().lower()
        dob_str = args.get("dob", "").strip()

        if not dob_str:
            return {
                "found": False,
                "message": "Date of birth is required to verify a patient. Please provide first name, last name, and date of birth.",
            }

        matches = []
        for p in db["patients"].values():
            if first and first not in p.first_name.lower():
                continue
            if last and last not in p.last_name.lower():
                continue
            try:
                if p.dob != date.fromisoformat(dob_str):
                    continue
            except ValueError:
                return {
                    "found": False,
                    "message": f"Invalid date of birth format: '{dob_str}'. Use YYYY-MM-DD.",
                }
            matches.append(p)

        if not matches:
            return {
                "found": False,
                "message": "No patient found. Please check the name and date of birth.",
            }

        p = matches[0]
        session["patient_id"] = p.id
        session["patient_confirmed"] = True

        return {
            "found": True,
            "patient_id": p.id,
            "name": f"{p.first_name} {p.last_name}",
            "dob": p.dob.isoformat(),
            "referrals": [
                {
                    "specialty": r.specialty,
                    "provider": r.provider_name or "Not specified",
                }
                for r in p.referred_providers
            ],
        }


registry.register(VerifyPatientTool())
