"""
Insurance verification and self-pay rate API routes.
"""

from flask import Blueprint, current_app, jsonify

insurance_bp = Blueprint("insurance", __name__)


@insurance_bp.route("/api/insurance/check/<plan>", methods=["GET"])
def check_insurance(plan):
    db = current_app.config["db"]
    normalised = plan.strip().lower()
    accepted = any(
        p.lower() == normalised for p in db["insurance"].accepted_plans
    )
    result: dict = {"plan": plan, "accepted": accepted}
    if not accepted:
        result["self_pay_available"] = True
        result["message"] = "Plan not accepted. Self-pay rates available."
    result["self_pay_rates"] = db["insurance"].self_pay_rates
    return jsonify(result)


@insurance_bp.route("/api/insurance/selfpay/<specialty>", methods=["GET"])
def get_selfpay(specialty):
    db = current_app.config["db"]
    rate = db["insurance"].self_pay_rates.get(specialty)
    if rate is None:
        for key, val in db["insurance"].self_pay_rates.items():
            if key.lower() == specialty.lower():
                rate = val
                specialty = key
                break
    if rate is None:
        return jsonify({"error": f"No self-pay rate for {specialty}"}), 404
    return jsonify({"specialty": specialty, "rate": rate})
