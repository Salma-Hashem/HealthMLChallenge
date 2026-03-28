"""
Tool definitions and executors for the Care Coordinator Assistant.

Tool schemas are defined in a provider-agnostic JSON format and converted
to Gemini FunctionDeclarations at runtime. Each tool validates inputs and
returns a JSON string that is passed back to the LLM as a tool result.
"""

import json
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from models import Appointment
from policy_engine import (
    determine_appointment_type,
    get_appointment_duration,
    get_arrival_instructions,
    get_last_seen_date,
    validate_booking_request,
)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "verify_patient",
        "description": (
            "Search for a patient by name and/or date of birth to verify their identity. "
            "ALWAYS call this first — before any patient-specific action. "
            "On success, updates the session so patient-specific tools become available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "first_name": {
                    "type": "string",
                    "description": "Patient's first name (partial match supported)",
                },
                "last_name": {
                    "type": "string",
                    "description": "Patient's last name (partial match supported)",
                },
                "dob": {
                    "type": "string",
                    "description": "Date of birth in YYYY-MM-DD format (e.g. '1975-01-01')",
                },
            },
            "required": [],
        },
    },
    {
        "name": "lookup_provider_info",
        "description": (
            "Find providers by name or specialty. Use when the nurse mentions a provider "
            "by name or only gives a specialty. Returns provider IDs, departments, "
            "locations, office hours, and contact info."
        ),
        "input_schema": {
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
        },
    },
    {
        "name": "get_booking_history",
        "description": (
            "Check whether a patient has seen a specific provider before and determine "
            "the correct appointment type (NEW or ESTABLISHED). "
            "ALWAYS call this before searching for slots — it tells you the required duration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "Patient ID returned by verify_patient",
                },
                "provider_id": {
                    "type": "integer",
                    "description": "Provider ID returned by lookup_provider_info",
                },
            },
            "required": ["patient_id", "provider_id"],
        },
    },
    {
        "name": "find_available_slots",
        "description": (
            "Search for available appointment slots for a provider at a given location. "
            "Filter by duration: use 30 for NEW patients, 15 for ESTABLISHED. "
            "Returns up to 20 slots grouped by day. "
            "IMPORTANT: always search the full default window (today → 28 days). "
            "Do NOT narrow the date range to match a time-of-day preference — "
            "filter the returned results instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "integer",
                    "description": "Provider ID",
                },
                "location_id": {
                    "type": "integer",
                    "description": "Department/location ID (omit to search all locations for this provider)",
                },
                "duration": {
                    "type": "integer",
                    "description": "Required slot duration in minutes: 30 for NEW, 15 for ESTABLISHED",
                    "enum": [15, 30],
                },
                "date_from": {
                    "type": "string",
                    "description": "Start of search window in YYYY-MM-DD format (defaults to today)",
                },
                "date_to": {
                    "type": "string",
                    "description": "End of search window in YYYY-MM-DD format (defaults to 14 days from today)",
                },
            },
            "required": ["provider_id", "duration"],
        },
    },
    {
        "name": "list_alternative_providers",
        "description": (
            "Find other providers in the same specialty when the preferred provider "
            "is unavailable or has no open slots at the requested time. "
            "Pass patient_id and duration to get next available slots and patient history "
            "(e.g. 'patient saw Dr. Jones in 2022') for each alternative — "
            "use this to give the nurse instant 'No, but...' alternatives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialty": {
                    "type": "string",
                    "description": "Medical specialty (e.g. 'Orthopedics', 'Primary Care')",
                },
                "exclude_provider_id": {
                    "type": "integer",
                    "description": "Provider ID to exclude (the unavailable provider)",
                },
                "patient_id": {
                    "type": "integer",
                    "description": "Patient ID — when provided, includes whether patient has seen each alternative provider before",
                },
                "duration": {
                    "type": "integer",
                    "description": "Slot duration in minutes (15 or 30) — when provided, returns next available slots of that duration per provider",
                    "enum": [15, 30],
                },
            },
            "required": ["specialty"],
        },
    },
    {
        "name": "check_provider_availability",
        "description": (
            "Get a provider's full profile: all departments, locations, office hours, "
            "and contact info. Use to understand when and where a provider is available "
            "before searching for slots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider_id": {
                    "type": "integer",
                    "description": "Provider ID",
                },
            },
            "required": ["provider_id"],
        },
    },
    {
        "name": "verify_insurance",
        "description": (
            "Check whether a patient's insurance plan is accepted by the hospital. "
            "If not accepted, self-pay rates are returned so the nurse can be informed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_name": {
                    "type": "string",
                    "description": (
                        "Insurance plan name exactly as stated by the nurse "
                        "(e.g. 'Blue Cross Blue Shield of North Carolina', 'Aetna', 'Cigna')"
                    ),
                },
            },
            "required": ["plan_name"],
        },
    },
    {
        "name": "get_selfpay_rate",
        "description": (
            "Get the self-pay cost for a medical specialty. "
            "Use when insurance is not accepted so the nurse knows out-of-pocket costs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialty": {
                    "type": "string",
                    "description": "Medical specialty (e.g. 'Orthopedics', 'Primary Care', 'Surgery')",
                },
            },
            "required": ["specialty"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "FINALIZE an appointment booking after the nurse has explicitly confirmed. "
            "ONLY call this after the nurse says 'yes', 'confirm', 'book it', or similar. "
            "This action is irreversible — it marks the slot as taken and issues a confirmation number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "integer",
                    "description": "Patient ID from verify_patient",
                },
                "slot_id": {
                    "type": "string",
                    "description": "Slot ID from find_available_slots",
                },
                "appointment_type": {
                    "type": "string",
                    "description": "Appointment type from get_booking_history: 'NEW' or 'ESTABLISHED'",
                    "enum": ["NEW", "ESTABLISHED"],
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for the visit (e.g. 'Orthopedics referral post-discharge')",
                },
            },
            "required": ["patient_id", "slot_id", "appointment_type"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_tool(name: str, tool_input: dict, db: dict, session: dict) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    try:
        if name == "verify_patient":
            return _verify_patient(tool_input, db, session)
        if name == "lookup_provider_info":
            return _lookup_provider_info(tool_input, db)
        if name == "get_booking_history":
            return _get_booking_history(tool_input, db)
        if name == "find_available_slots":
            return _find_available_slots(tool_input, db)
        if name == "list_alternative_providers":
            return _list_alternative_providers(tool_input, db)
        if name == "check_provider_availability":
            return _check_provider_availability(tool_input, db)
        if name == "verify_insurance":
            return _verify_insurance(tool_input, db)
        if name == "get_selfpay_rate":
            return _get_selfpay_rate(tool_input, db)
        if name == "book_appointment":
            return _book_appointment(tool_input, db, session)
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as exc:
        return json.dumps({"error": f"Tool execution failed: {str(exc)}"})


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _verify_patient(inp: dict, db: dict, session: dict) -> str:
    first = inp.get("first_name", "").strip().lower()
    last = inp.get("last_name", "").strip().lower()
    dob_str = inp.get("dob", "").strip()

    matches = []
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
        matches.append(p)

    if not matches:
        return json.dumps({"found": False, "message": "No patient found. Please check the name and date of birth."})

    p = matches[0]
    # Update session state
    session["patient_id"] = p.id
    session["patient_confirmed"] = True

    return json.dumps({
        "found": True,
        "patient_id": p.id,
        "name": f"{p.first_name} {p.last_name}",
        "dob": p.dob.isoformat(),
        "insurance": p.insurance,
        "referrals": [
            {"specialty": r.specialty, "provider": r.provider_name or "Not specified"}
            for r in p.referred_providers
        ],
    })


def _lookup_provider_info(inp: dict, db: dict) -> str:
    name_q = inp.get("name", "").strip().lower()
    spec_q = inp.get("specialty", "").strip().lower()

    matches = []
    for p in db["providers"].values():
        if name_q and name_q not in p.last_name.lower() and name_q not in p.full_name.lower():
            continue
        if spec_q and spec_q not in p.specialty.lower():
            continue
        matches.append(p)

    if not matches:
        return json.dumps({"found": False, "message": "No providers found matching that name or specialty."})

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
    return json.dumps(result)


def _get_booking_history(inp: dict, db: dict) -> str:
    patient_id = int(inp["patient_id"])
    provider_id = int(inp["provider_id"])

    last_seen = get_last_seen_date(patient_id, provider_id, db["appointments"])
    appt_type = determine_appointment_type(last_seen)
    duration = get_appointment_duration(appt_type)
    arrival = get_arrival_instructions(appt_type)

    return json.dumps({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "last_seen_date": last_seen.isoformat() if last_seen else None,
        "appointment_type": appt_type,
        "required_duration_minutes": duration,
        "arrival_instructions": arrival,
    })


def _find_available_slots(inp: dict, db: dict) -> str:
    provider_id = int(inp["provider_id"])
    location_id = inp.get("location_id")
    if location_id is not None:
        location_id = int(location_id)
    duration = inp.get("duration")

    today = date.today()
    date_from = datetime.combine(today, datetime.min.time())
    date_to = datetime.combine(today + timedelta(days=28), datetime.max.time().replace(microsecond=0))

    if inp.get("date_from"):
        date_from = datetime.fromisoformat(inp["date_from"])
    if inp.get("date_to"):
        date_to = datetime.fromisoformat(inp["date_to"])

    matching = []
    for slot in db["slots"].values():
        if not slot.is_available:
            continue
        if slot.provider_id != provider_id:
            continue
        if location_id is not None and slot.department_id != location_id:
            continue
        if duration is not None and slot.duration_minutes != int(duration):
            continue
        if slot.start < date_from or slot.start > date_to:
            continue
        matching.append(slot)

    if not matching:
        # If a specific location was requested, check if the provider has slots elsewhere
        if location_id is not None:
            other_slots = [
                s for s in db["slots"].values()
                if s.is_available
                and s.provider_id == provider_id
                and s.department_id != location_id
                and (duration is None or s.duration_minutes == int(duration))
                and date_from <= s.start <= date_to
            ]
            if other_slots:
                other_slots.sort(key=lambda s: s.start)
                seen_locs: dict = {}
                for s in other_slots:
                    if s.department_id not in seen_locs:
                        dept = db["departments"].get(s.department_id)
                        seen_locs[s.department_id] = {
                            "location_id": s.department_id,
                            "location_name": dept.name if dept else "Unknown",
                            "address": dept.address if dept else "",
                            "phone": dept.phone if dept else "",
                            "next_slot_date": s.start.strftime("%A, %B %d"),
                            "next_slot_time": s.start.strftime("%I:%M %p"),
                            "next_slot_id": s.id,
                        }
                return json.dumps({
                    "found": False,
                    "message": (
                        "No slots at the requested location, but this provider has "
                        "availability at other locations they practice at."
                    ),
                    "provider_available_at_other_locations": list(seen_locs.values()),
                })
        return json.dumps({"found": False, "message": "No available slots found for the given criteria."})

    matching.sort(key=lambda s: s.start)

    grouped: dict = {}
    for slot in matching[:40]:
        day_key = slot.start.strftime("%A, %B %d, %Y")
        dept = db["departments"].get(slot.department_id)
        if day_key not in grouped:
            grouped[day_key] = []
        grouped[day_key].append({
            "slot_id": slot.id,
            "time": slot.start.strftime("%I:%M %p"),
            "duration_minutes": slot.duration_minutes,
            "location": dept.name if dept else "Unknown",
            "address": dept.address if dept else "",
        })

    return json.dumps({"total_available": len(matching), "slots_shown": min(40, len(matching)), "slots": grouped})


def _list_alternative_providers(inp: dict, db: dict) -> str:
    specialty = inp["specialty"].strip()
    exclude_id = inp.get("exclude_provider_id")
    patient_id = inp.get("patient_id")
    duration = inp.get("duration")

    today = date.today()
    date_from = datetime.combine(today, datetime.min.time())
    date_to = datetime.combine(today + timedelta(days=28), datetime.max.time().replace(microsecond=0))

    matches = []
    for p in db["providers"].values():
        if p.specialty.lower() != specialty.lower():
            continue
        if exclude_id is not None and p.id == int(exclude_id):
            continue

        depts = [{"location_id": d.id, "name": d.name, "address": d.address, "phone": d.phone}
                 for d in p.departments]
        entry: dict = {"provider_id": p.id, "name": p.display_name, "specialty": p.specialty, "departments": depts}

        # Patient history — tells the nurse if the patient has seen this provider before
        if patient_id is not None:
            last_seen = get_last_seen_date(int(patient_id), p.id, db["appointments"])
            appt_type = determine_appointment_type(last_seen)
            entry["patient_history"] = {
                "last_seen_date": last_seen.isoformat() if last_seen else None,
                "appointment_type": appt_type,
            }

        # Next available slots so the nurse gets instant "No, but..." alternatives
        slot_duration = int(duration) if duration is not None else None
        provider_slots = [
            s for s in db["slots"].values()
            if s.is_available
            and s.provider_id == p.id
            and (slot_duration is None or s.duration_minutes == slot_duration)
            and date_from <= s.start <= date_to
        ]
        provider_slots.sort(key=lambda s: s.start)
        next_slots = []
        for s in provider_slots[:3]:
            dept = db["departments"].get(s.department_id)
            next_slots.append({
                "slot_id": s.id,
                "date": s.start.strftime("%A, %B %d"),
                "time": s.start.strftime("%I:%M %p"),
                "duration_minutes": s.duration_minutes,
                "location": dept.name if dept else "Unknown",
                "address": dept.address if dept else "",
            })
        entry["next_available_slots"] = next_slots

        matches.append(entry)

    if not matches:
        return json.dumps({"found": False, "message": f"No alternative providers found for specialty: {specialty}"})
    return json.dumps(matches)


def _check_provider_availability(inp: dict, db: dict) -> str:
    provider_id = int(inp["provider_id"])
    p = db["providers"].get(provider_id)
    if not p:
        return json.dumps({"found": False, "message": f"Provider {provider_id} not found."})

    depts = []
    for d in p.departments:
        depts.append({
            "location_id": d.id,
            "name": d.name,
            "address": d.address,
            "phone": d.phone,
            "hours": [oh.to_dict() for oh in d.hours],
        })
    return json.dumps({"provider_id": p.id, "name": p.display_name, "specialty": p.specialty, "departments": depts})


_INSURANCE_ALIASES: dict[str, list[str]] = {
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


def _resolve_plan_name(plan: str, accepted_plans: list) -> str:
    """Return the canonical accepted plan name that best matches the input,
    or the original input if no match is found."""
    plan_lower = plan.lower().strip()

    # 1. Exact case-insensitive match
    for p in accepted_plans:
        if p.lower() == plan_lower:
            return p

    # 2. Alias lookup
    for canonical, aliases in _INSURANCE_ALIASES.items():
        if plan_lower in aliases:
            return canonical

    # 3. Substring match — input is contained in an accepted plan name
    for p in accepted_plans:
        if plan_lower in p.lower():
            return p

    # 4. Accepted plan name is contained in input (e.g. "Aetna Health Plan" → "Aetna")
    for p in accepted_plans:
        if p.lower() in plan_lower:
            return p

    return plan  # no match — return original so rejection is accurate


def _verify_insurance(inp: dict, db: dict) -> str:
    raw_plan = inp["plan_name"].strip()
    resolved = _resolve_plan_name(raw_plan, db["insurance"].accepted_plans)
    accepted = any(p.lower() == resolved.lower() for p in db["insurance"].accepted_plans)

    result: dict = {
        "plan_as_entered": raw_plan,
        "plan_matched": resolved,
        "accepted": accepted,
    }
    if not accepted:
        result["message"] = "This insurance plan is not accepted. Self-pay rates are available."
        result["self_pay_rates"] = db["insurance"].self_pay_rates
    return json.dumps(result)


def _get_selfpay_rate(inp: dict, db: dict) -> str:
    specialty = inp["specialty"].strip()
    rates = db["insurance"].self_pay_rates
    rate = rates.get(specialty)
    if rate is None:
        for k, v in rates.items():
            if k.lower() == specialty.lower():
                rate = v
                specialty = k
                break
    if rate is None:
        return json.dumps({"found": False, "message": f"No self-pay rate found for: {specialty}"})
    return json.dumps({"specialty": specialty, "rate": rate, "currency": "USD"})


def _book_appointment(inp: dict, db: dict, session: dict) -> str:
    patient_id = int(inp["patient_id"])
    slot_id = str(inp["slot_id"])
    appt_type = str(inp.get("appointment_type", "NEW"))
    reason = str(inp.get("reason", ""))

    validation = validate_booking_request(
        patient_id, slot_id, appt_type,
        db["slots"], db["patients"], db["appointments"],
        db["departments"], db["providers"],
    )

    if not validation["valid"]:
        return json.dumps({"success": False, "errors": validation["errors"]})

    slot = db["slots"][slot_id]
    slot.is_available = False
    corrected_type = validation["corrected_type"]

    confirmation = f"CCA-{uuid.uuid4().hex[:8].upper()}"
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

    provider = db["providers"].get(slot.provider_id)
    dept = db["departments"].get(slot.department_id)

    # Mark active referral as booked in session
    ref = _active_referral(session)
    if ref is not None:
        ref["booked"] = True
        ref["confirmation_number"] = confirmation
        ref["appointment_type"] = corrected_type
        ref["slot_id"] = slot_id

    return json.dumps({
        "success": True,
        "confirmation_number": confirmation,
        "patient_id": patient_id,
        "provider": provider.display_name if provider else "Unknown",
        "department": dept.name if dept else "Unknown",
        "address": dept.address if dept else "",
        "phone": dept.phone if dept else "",
        "date": slot.start.strftime("%A, %B %d, %Y"),
        "time": slot.start.strftime("%I:%M %p"),
        "duration_minutes": slot.duration_minutes,
        "appointment_type": corrected_type,
        "arrival_instructions": get_arrival_instructions(corrected_type),
        "warnings": validation.get("warnings", []),
    })


def _active_referral(session: dict) -> Optional[dict]:
    idx = session.get("active_referral_index", 0)
    refs = session.get("referrals", [])
    return refs[idx] if 0 <= idx < len(refs) else None


# ---------------------------------------------------------------------------
# OpenAI / Groq tool format conversion
# ---------------------------------------------------------------------------

def get_openai_tools() -> list:
    """Return tools in OpenAI function-calling format (compatible with Groq)."""
    result = []
    for tool in TOOLS:
        schema = dict(tool["input_schema"])
        # Remove empty required list — OpenAI treats missing as no required fields
        if "required" in schema and not schema["required"]:
            del schema["required"]
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": schema,
            },
        })
    return result
