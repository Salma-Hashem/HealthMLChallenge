"""
Flask API for the Care Coordinator Assistant.

Exposes REST endpoints for patient search, provider lookup, slot search,
appointment booking, insurance verification, and workflow session management.
"""

import os
import uuid
from datetime import date, datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

load_dotenv()

from models import Appointment, BookingConfirmation
from data_loader import load_all_data
from slot_generator import generate_slots
from policy_engine import (
    determine_appointment_type,
    get_appointment_duration,
    get_arrival_instructions,
    get_last_seen_date,
    validate_booking_request,
)
from workflow import (
    WorkflowState,
    create_session,
    get_required_fields,
    can_advance,
    advance,
    add_referral,
    get_session_summary,
    transition_to,
)

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
app = Flask(__name__, static_folder=FRONTEND_DIST, static_url_path="")

DATA_SHEET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data_sheet.txt"
)
db = load_all_data(DATA_SHEET_PATH)
db["slots"] = generate_slots(db["providers"], db["departments"], num_days=28)

sessions = {}
_next_appt_id = max((a.id for a in db["appointments"]), default=0) + 1


# ---------------------------------------------------------------------------
# Backward-compatible endpoints
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def healthcheck():
    return jsonify({"status": "ok", "service": "Care Coordinator Assistant"})


@app.route("/api/health", methods=["GET"])
def api_health():
    """Health check endpoint used by Docker and load balancers."""
    api_key_set = bool(os.environ.get("CEREBRAS_API_KEY"))
    if not api_key_set:
        return jsonify({
            "status": "degraded",
            "reason": "CEREBRAS_API_KEY is not set — chat endpoint will not function. "
                      "Set it in your .env file (see .env.example).",
        }), 503
    return jsonify({
        "status": "ok",
        "service": "Care Coordinator Assistant",
        "llm": "cerebras/qwen-3-235b",
        "patients": len(db.get("patients", {})),
        "providers": len(db.get("providers", {})),
    })


@app.route("/patient/<patient_id>", methods=["GET"])
def get_patient_legacy(patient_id):
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


# ---------------------------------------------------------------------------
# New structured API
# ---------------------------------------------------------------------------

@app.route("/api/patient/<int:patient_id>", methods=["GET"])
def get_patient(patient_id):
    patient = db["patients"].get(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    return jsonify(_serialize_patient(patient))


@app.route("/api/patient/search", methods=["POST"])
def search_patient():
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
        results.append(_serialize_patient(p))
    return jsonify(results)


@app.route("/api/providers", methods=["GET"])
def list_providers():
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
        results.append(_serialize_provider(p))
    return jsonify(results)


@app.route("/api/providers/<int:provider_id>", methods=["GET"])
def get_provider(provider_id):
    provider = db["providers"].get(provider_id)
    if not provider:
        return jsonify({"error": "Provider not found"}), 404
    return jsonify(_serialize_provider(provider, include_hours=True))


@app.route("/api/history/<int:patient_id>/<int:provider_id>", methods=["GET"])
def get_history(patient_id, provider_id):
    last_seen = get_last_seen_date(patient_id, provider_id, db["appointments"])
    appt_type = determine_appointment_type(last_seen)
    duration = get_appointment_duration(appt_type)

    return jsonify({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "last_seen_date": last_seen.isoformat() if last_seen else None,
        "appointment_type": appt_type,
        "duration_minutes": duration,
    })


@app.route("/api/slots/search", methods=["POST"])
def search_slots():
    data = request.get_json() or {}
    provider_id = data.get("provider_id")
    location_id = data.get("location_id")
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    duration = data.get("duration")

    results = []
    for slot in db["slots"].values():
        if provider_id is not None and slot.provider_id != provider_id:
            continue
        if location_id is not None and slot.department_id != location_id:
            continue
        if duration is not None and slot.duration_minutes != duration:
            continue
        if date_from:
            if slot.start < datetime.fromisoformat(date_from):
                continue
        if date_to:
            if slot.start > datetime.fromisoformat(date_to):
                continue
        results.append(_serialize_slot(slot))

    results.sort(key=lambda s: s["start"])
    return jsonify(results)


@app.route("/api/appointments/book", methods=["POST"])
def book_appointment():
    global _next_appt_id
    data = request.get_json() or {}
    patient_id = data.get("patient_id")
    slot_id = data.get("slot_id")
    appt_type = data.get("type", "NEW")
    reason = data.get("reason", "")

    validation = validate_booking_request(
        patient_id,
        slot_id,
        appt_type,
        db["slots"],
        db["patients"],
        db["appointments"],
        db["departments"],
        db["providers"],
    )

    if not validation["valid"]:
        return jsonify({
            "error": "Booking validation failed",
            "details": validation["errors"],
        }), 400

    slot = db["slots"][slot_id]
    slot.is_available = False

    confirmation = f"CCA-{uuid.uuid4().hex[:8].upper()}"
    corrected_type = validation["corrected_type"]

    appointment = Appointment(
        id=_next_appt_id,
        patient_id=patient_id,
        provider_id=slot.provider_id,
        date=slot.start.date(),
        time=slot.start.time(),
        status="booked",
        confirmation_number=confirmation,
        appointment_type=corrected_type,
        reason=reason,
    )
    _next_appt_id += 1
    db["appointments"].append(appointment)

    return jsonify({
        "confirmation_number": confirmation,
        "appointment": {
            "id": appointment.id,
            "patient_id": patient_id,
            "provider_id": slot.provider_id,
            "department_id": slot.department_id,
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "type": corrected_type,
            "reason": reason,
        },
        "arrival_instructions": get_arrival_instructions(corrected_type),
        "warnings": validation.get("warnings", []),
    }), 201


@app.route("/api/insurance/check/<plan>", methods=["GET"])
def check_insurance(plan):
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


@app.route("/api/insurance/selfpay/<specialty>", methods=["GET"])
def get_selfpay(specialty):
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


# ---------------------------------------------------------------------------
# Chat endpoint (LLM-powered, Issue #13)
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def chat():
    from orchestrator import handle_message
    data = request.get_json() or {}
    session_id = data.get("session_id") or None
    message = (data.get("message") or "").strip()
    regenerate = bool(data.get("regenerate", False))

    if not message:
        return jsonify({"error": "Message cannot be empty"}), 400

    try:
        result = handle_message(session_id, message, db, sessions, regenerate=regenerate)
        return jsonify(result)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {str(exc)}"}), 500


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """Record thumbs-up/down feedback for a specific assistant message.

    Appends one JSON line to feedback.jsonl (POC storage).
    No patient data — session_id and message_index only.
    """
    import json as _json
    from datetime import datetime, timezone

    data = request.get_json() or {}
    session_id = data.get("session_id")
    message_index = data.get("message_index")
    feedback_val = data.get("feedback")          # "positive" | "negative" | null
    workflow_state = data.get("workflow_state", "")
    tool_calls = data.get("tool_calls_in_turn", [])
    # Truncate response preview to 500 chars; never store full patient data
    response_preview = (data.get("response_text") or "")[:500]

    if feedback_val not in ("positive", "negative", None):
        return jsonify({"error": "feedback must be 'positive', 'negative', or null"}), 400

    entry = {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "session_id":       session_id,
        "message_index":    message_index,
        "feedback":         feedback_val,
        "workflow_state":   workflow_state,
        "tool_calls_in_turn": tool_calls,
        "response_preview": response_preview,
    }

    feedback_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback.jsonl")
    with open(feedback_path, "a", encoding="utf-8") as fh:
        fh.write(_json.dumps(entry) + "\n")

    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Workflow / session endpoints
# ---------------------------------------------------------------------------

@app.route("/api/session", methods=["POST"])
def create_new_session():
    session = create_session()
    sessions[session["session_id"]] = session
    return jsonify({
        "session_id": session["session_id"],
        "state": session["state"].value,
    }), 201


@app.route("/api/session/<session_id>", methods=["GET"])
def get_session(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_serialize_session(session))


@app.route("/api/session/<session_id>/advance", methods=["POST"])
def advance_session(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    try:
        advance(session)
        return jsonify(_serialize_session(session))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialize_patient(patient):
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


def _serialize_provider(provider, include_hours=False):
    departments = []
    for d in provider.departments:
        dept: dict = {
            "id": d.id,
            "name": d.name,
            "phone": d.phone,
            "address": d.address,
        }
        if include_hours:
            dept["hours"] = [oh.to_dict() for oh in d.hours]
        departments.append(dept)

    return {
        "id": provider.id,
        "first_name": provider.first_name,
        "last_name": provider.last_name,
        "certification": provider.certification,
        "specialty": provider.specialty,
        "departments": departments,
    }


def _serialize_slot(slot):
    return {
        "id": slot.id,
        "provider_id": slot.provider_id,
        "department_id": slot.department_id,
        "start": slot.start.isoformat(),
        "end": slot.end.isoformat(),
        "duration_minutes": slot.duration_minutes,
        "is_available": slot.is_available,
    }


def _serialize_session(session):
    return {
        "session_id": session["session_id"],
        "state": session["state"].value,
        "patient_id": session["patient_id"],
        "patient_confirmed": session["patient_confirmed"],
        "referrals": session["referrals"],
        "active_referral_index": session["active_referral_index"],
        "completed_bookings": session["completed_bookings"],
    }


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the React SPA. API routes take priority (registered first)."""
    if path and os.path.exists(os.path.join(FRONTEND_DIST, path)):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
