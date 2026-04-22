"""
Tool: verify_insurance

Checks whether a patient's insurance plan is accepted. Includes fuzzy
matching so common abbreviations (BCBS, UHC, etc.) resolve to the full
canonical plan name before the acceptance check runs.
"""

from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import VerifyInsuranceArgs, schema_for

# ---------------------------------------------------------------------------
# Alias table — maps lowercase abbreviations/variants to canonical plan names
# ---------------------------------------------------------------------------
_ALIASES: dict[str, list[str]] = {
    "Blue Cross Blue Shield of North Carolina": [
        "bcbs", "blue cross", "blue shield", "blue cross blue shield",
        "bcbs nc", "bcbs of nc", "blue cross nc", "bluecross blueshield",
        "blue cross & blue shield",
    ],
    "United Health Care": [
        "united", "uhc", "united healthcare", "united health",
        "unitedhealthcare",
    ],
    "Medicaid": [
        "medicaid nc", "nc medicaid",
    ],
    "Aetna": [
        "aetna health", "aetna inc",
    ],
    "Cigna": [
        "cigna health", "cigna healthcare",
    ],
}


def _resolve_plan(plan: str, accepted: list[str]) -> str:
    """Return the canonical accepted plan name that best matches *plan*.

    Resolution order:
      1. Exact case-insensitive match.
      2. Alias lookup (common abbreviations).
      3. Input substring contained in an accepted plan name.
      4. Accepted plan name contained in the input.
      5. Original input (no match found — will result in rejection).
    """
    lower = plan.lower().strip()

    for p in accepted:
        if p.lower() == lower:
            return p

    for canonical, aliases in _ALIASES.items():
        if lower in aliases:
            return canonical

    for p in accepted:
        if lower in p.lower():
            return p

    for p in accepted:
        if p.lower() in lower:
            return p

    return plan


class VerifyInsuranceTool(BaseTool):
    name = "verify_insurance"
    description = (
        "Check whether a patient's insurance plan is accepted by the hospital. "
        "If not accepted, self-pay rates are returned so the nurse can be informed."
    )
    schema = schema_for(VerifyInsuranceArgs)
    requires_patient_verification = False

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        raw = args["plan_name"].strip()
        resolved = _resolve_plan(raw, db["insurance"].accepted_plans)
        accepted = any(p.lower() == resolved.lower() for p in db["insurance"].accepted_plans)

        result: dict = {
            "plan_as_entered": raw,
            "plan_matched": resolved,
            "accepted": accepted,
        }
        if not accepted:
            result["message"] = "This insurance plan is not accepted. Self-pay rates are available."
            result["self_pay_rates"] = db["insurance"].self_pay_rates
        return result


registry.register(VerifyInsuranceTool())
