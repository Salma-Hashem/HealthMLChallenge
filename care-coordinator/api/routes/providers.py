"""
Provider-related API routes.
"""

from flask import Blueprint, current_app, jsonify, request

from api.serializers import serialize_provider

providers_bp = Blueprint("providers", __name__)


@providers_bp.route("/api/providers", methods=["GET"])
def list_providers():
    db = current_app.config["db"]
    specialty = request.args.get("specialty")
    location = request.args.get("location")
    department = request.args.get("department")

    results = []
    for p in db["providers"].values():
        if specialty and p.specialty.lower() != specialty.lower():
            continue
        if department and not any(
            d.name.lower() == department.lower() for d in p.departments
        ):
            continue
        if location and not any(
            location.lower() in d.address.lower() for d in p.departments
        ):
            continue
        results.append(serialize_provider(p))
    return jsonify(results)


@providers_bp.route("/api/providers/<int:provider_id>", methods=["GET"])
def get_provider(provider_id):
    db = current_app.config["db"]
    provider = db["providers"].get(provider_id)
    if not provider:
        return jsonify({"error": "Provider not found"}), 404
    return jsonify(serialize_provider(provider, include_hours=True))
