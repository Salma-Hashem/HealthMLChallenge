"""
Patient-related API routes.
"""

from datetime import date

from flask import Blueprint, current_app, jsonify, request

from api.serializers import serialize_patient

patients_bp = Blueprint("patients", __name__)


@patients_bp.route("/patient/<patient_id>", methods=["GET"])
def get_patient_legacy(patient_id):
    """Legacy endpoint — kept for backward compatibility with older clients."""
    db = current_app.config["db"]
    pid = int(patient_id)
    patient = db["patients"].get(pid)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404

    appt_list = []
    for appt in db["appointments"]:
        if appt.patient_id == pid:
            provider = db["providers"].get(appt.provider_id)
            pname = provider.display_name if provider else "Unknown"
            appt_list.append({
                "date": appt.date.strftime("%-m/%d/%y"),
                "time": appt.time.strftime("%-I:%M%p").lower(),
                "provider": pname,
                "status": appt.status,
            })

    referred = []
    for ref in patient.referred_providers:
        entry: dict = {"specialty": ref.specialty}
        if ref.provider_name:
            entry["provider"] = ref.provider_name
        referred.append(entry)

    return jsonify({
        "id": patient.id,
        "name": f"{patient.first_name} {patient.last_name}",
        "dob": patient.dob.strftime("%m/%d/%Y"),
        "pcp": patient.pcp,
        "ehrId": patient.ehr_id,
        "referred_providers": referred,
        "appointments": appt_list,
    })


@patients_bp.route("/api/patient/<int:patient_id>", methods=["GET"])
def get_patient(patient_id):
    db = current_app.config["db"]
    patient = db["patients"].get(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    return jsonify(serialize_patient(patient))


@patients_bp.route("/api/patient/search", methods=["POST"])
def search_patient():
    db = current_app.config["db"]
    data = request.get_json() or {}
    first = data.get("first_name", "").lower()
    last = data.get("last_name", "").lower()
    dob_str = data.get("dob")

    results = []
    for p in db["patients"].values():
        if first and first not in p.first_name.lower():
            continue
        if last and last not in p.last_name.lower():
            continue
        if dob_str:
            try:
                if p.dob != date.fromisoformat(dob_str):
                    continue
            except ValueError:
                pass
        results.append(serialize_patient(p))
    return jsonify(results)
