"""
Tool: get_selfpay_rate

Returns the self-pay cost for a medical specialty. Used when a patient's
insurance is not accepted so the nurse can inform them of out-of-pocket costs.
"""

from tools.base import BaseTool
from tools.registry import registry
from tools.schemas import GetSelfpayRateArgs, schema_for


class GetSelfpayRateTool(BaseTool):
    name = "get_selfpay_rate"
    description = (
        "Get the self-pay cost for a medical specialty. "
        "Use when insurance is not accepted so the nurse knows out-of-pocket costs."
    )
    schema = schema_for(GetSelfpayRateArgs)
    requires_patient_verification = False

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        specialty = args["specialty"].strip()
        rates = db["insurance"].self_pay_rates

        rate = rates.get(specialty)
        if rate is None:
            for k, v in rates.items():
                if k.lower() == specialty.lower():
                    rate = v
                    specialty = k
                    break

        if rate is None:
            return {"found": False, "message": f"No self-pay rate found for: {specialty}"}
        return {"found": True, "specialty": specialty, "rate": rate, "currency": "USD"}


registry.register(GetSelfpayRateTool())
