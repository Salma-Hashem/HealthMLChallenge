"""
Tool: check_provider_availability

Returns a provider's full profile: all departments, locations, office hours,
and contact info. Used before slot searches to understand where/when a
provider practices.
"""

from tools.base import BaseTool
from tools.registry import registry


class CheckProviderAvailabilityTool(BaseTool):
    name = "check_provider_availability"
    description = (
        "Get a provider's full profile: all departments, locations, office hours, "
        "and contact info. Use to understand when and where a provider is available "
        "before searching for slots."
    )
    schema = {
        "type": "object",
        "properties": {
            "provider_id": {
                "type": "integer",
                "description": "Provider ID",
            },
        },
        "required": ["provider_id"],
    }
    requires_patient_verification = True

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        provider_id = int(args["provider_id"])
        p = db["providers"].get(provider_id)
        if not p:
            return {"found": False, "message": f"Provider {provider_id} not found."}

        depts = [
            {
                "location_id": d.id,
                "name": d.name,
                "address": d.address,
                "phone": d.phone,
                "hours": [oh.to_dict() for oh in d.hours],
            }
            for d in p.departments
        ]
        return {
            "found": True,
            "provider_id": p.id,
            "name": p.display_name,
            "specialty": p.specialty,
            "departments": depts,
        }


registry.register(CheckProviderAvailabilityTool())
