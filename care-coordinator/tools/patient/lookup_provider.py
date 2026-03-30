"""
Tool: lookup_provider_info

Finds providers by name or specialty. Returns provider IDs, departments,
locations, office hours, and contact info.
"""

from tools.base import BaseTool
from tools.registry import registry


class LookupProviderTool(BaseTool):
    name = "lookup_provider_info"
    description = (
        "Find providers by name or specialty. Use when the nurse mentions a provider "
        "by name or only gives a specialty. Returns provider IDs, departments, "
        "locations, office hours, and contact info."
    )
    schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Provider last name or full name (e.g. 'House' or 'Gregory House')",
            },
            "specialty": {
                "type": "string",
                "description": "Medical specialty (e.g. 'Orthopedics', 'Primary Care', 'Surgery')",
            },
        },
        "required": [],
    }
    requires_patient_verification = False

    def execute(self, args: dict, db: dict, session: dict) -> list:
        name_q = args.get("name", "").strip().lower()
        spec_q = args.get("specialty", "").strip().lower()

        matches = []
        for p in db["providers"].values():
            if name_q and name_q not in p.last_name.lower() and name_q not in p.full_name.lower():
                continue
            if spec_q and spec_q not in p.specialty.lower():
                continue
            matches.append(p)

        if not matches:
            return {"found": False, "message": "No providers found matching that name or specialty."}

        result = []
        for p in matches:
            depts = []
            for d in p.departments:
                hours_summary = [
                    f"{oh.to_dict()['day']}: {oh.to_dict()['open']}–{oh.to_dict()['close']}"
                    for oh in d.hours
                ]
                depts.append({
                    "location_id": d.id,
                    "name": d.name,
                    "address": d.address,
                    "phone": d.phone,
                    "hours": hours_summary,
                })
            result.append({
                "provider_id": p.id,
                "name": p.display_name,
                "certification": p.certification,
                "specialty": p.specialty,
                "departments": depts,
            })
        return result


registry.register(LookupProviderTool())
