"""
Scheduling API routes: appointment history, slot search, and booking.
"""

import uuid
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, request

from api.serializers import serialize_slot
from core.models import Appointment
from core.policy import (
    determine_appointment_type,
    get_appointment_duration,
    get_arrival_instructions,
    get_last_seen_date,
    validate_booking_request,
)

scheduling_bp = Blueprint("scheduling", __name__)


@scheduling_bp.route("/api/history/<int:patient_id>/<int:provider_id>", methods=["GET"])
def get_history(patient_id, provider_id):
    db = current_app.config["db"]
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


@scheduling_bp.route("/api/slots/search", methods=["POST"])
def search_slots():
    db = current_app.config["db"]
    data = request.get_json() or {}
    provider_id = data.get("provider_id")
    location_id = data.get("location_id")
    date_from = data.get("date_from")
    date_to = data.get("date_to")
    duration = data.get("duration")

    slot_pool = (
        db.get("slots_by_provider", {}).get(provider_id)
        if provider_id is not None
        else None
    ) or list(db["slots"].values())

    results = []
    for slot in slot_pool:
        if provider_id is not None and slot.provider_id != provider_id:
            continue
        if location_id is not None and slot.department_id != location_id:
            continue
        if duration is not None and slot.duration_minutes != duration:
            continue
        try:
            if date_from and slot.start < datetime.fromisoformat(date_from):
                continue
            if date_to and slot.start > datetime.fromisoformat(date_to):
                continue
        except ValueError:
            return jsonify({"error": "Invalid date format. Use ISO 8601 (YYYY-MM-DD)."}), 400
        results.append(serialize_slot(slot))

    results.sort(key=lambda s: s["start"])
    return jsonify(results)


@scheduling_bp.route("/api/appointments/book", methods=["POST"])
def book_appointment():
    db = current_app.config["db"]
    data = request.get_json() or {}
    patient_id = data.get("patient_id")
    slot_id = data.get("slot_id")
    if patient_id is None or slot_id is None:
        return jsonify({"error": "patient_id and slot_id are required"}), 400
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
    next_id = max((a.id for a in db["appointments"]), default=0) + 1

    appointment = Appointment(
        id=next_id,
        patient_id=patient_id,
        provider_id=slot.provider_id,
        date=slot.start.date(),
        time=slot.start.time(),
        status="booked",
        confirmation_number=confirmation,
        appointment_type=corrected_type,
        reason=reason,
    )
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
