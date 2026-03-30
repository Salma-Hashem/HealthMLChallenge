"""
Tool: find_available_slots

Searches for available appointment slots for a provider, optionally filtered
by location and duration. When a specific location has no slots, automatically
checks the provider's other locations and surfaces them.

Internal helpers (all pure, independently testable):
    _resolve_date_window  — parse / default the date range from LLM args
    _filter_slots         — apply provider / location / duration / window criteria
    _find_alternative_locations — fallback search across the provider's other locations
    _group_by_day         — bucket a sorted slot list into a {day: [slot, …]} dict
"""

from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from tools.base import BaseTool
from tools.registry import registry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum number of slots to return to the LLM in a single response.
# Keeps the context window manageable while still covering a full week of
# common appointment patterns (e.g. 8 slots/day × 5 days = 40 slots).
MAX_SLOTS_RETURNED = 40

# Default search horizon in days when the caller does not specify date_to.
DEFAULT_WINDOW_DAYS = 28


# ---------------------------------------------------------------------------
# Pure helper: date window resolution
# ---------------------------------------------------------------------------

def _resolve_date_window(
    date_from_str: Optional[str],
    date_to_str: Optional[str],
) -> Tuple[datetime, datetime]:
    """Parse caller-supplied ISO date strings into a (date_from, date_to) window.

    Falls back to (today, today + DEFAULT_WINDOW_DAYS) for any missing or
    malformed value instead of propagating a ValueError to the caller.

    Args:
        date_from_str: Optional ISO-8601 date/datetime string for the start bound.
        date_to_str:   Optional ISO-8601 date/datetime string for the end bound.

    Returns:
        (date_from, date_to) as naive datetime objects.
    """
    today = date.today()

    # Default: start of today
    date_from = datetime.combine(today, datetime.min.time())
    # Default: end of day 28 days from today (microseconds stripped for clean comparison)
    date_to = datetime.combine(
        today + timedelta(days=DEFAULT_WINDOW_DAYS),
        datetime.max.time().replace(microsecond=0),
    )

    # Override defaults only when the caller provides a parseable value.
    # Malformed strings are silently ignored so the tool degrades gracefully
    # rather than surfacing a raw Python exception to the nurse.
    if date_from_str:
        try:
            date_from = datetime.fromisoformat(date_from_str)
        except ValueError:
            pass  # keep the default; bad input is better than a crash

    if date_to_str:
        try:
            date_to = datetime.fromisoformat(date_to_str)
        except ValueError:
            pass  # keep the default

    return date_from, date_to


# ---------------------------------------------------------------------------
# Pure helper: slot filtering
# ---------------------------------------------------------------------------

def _filter_slots(
    slots: dict,
    provider_id: int,
    date_from: datetime,
    date_to: datetime,
    location_id: Optional[int] = None,
    duration: Optional[int] = None,
) -> List:
    """Filter the slot dictionary down to candidates that match all criteria.

    Only available slots within the date window for the given provider are
    returned. location_id and duration are optional — omitting either widens
    the search to all locations / all durations for that provider.

    Args:
        slots:       db["slots"] dict keyed by slot ID.
        provider_id: The provider whose slots are being searched.
        date_from:   Inclusive lower bound of the search window.
        date_to:     Inclusive upper bound of the search window.
        location_id: If given, restrict results to this department only.
        duration:    If given, restrict results to slots of exactly this length.

    Returns:
        Unsorted list of matching slot objects.
    """
    matching = []
    for slot in slots.values():
        # Skip slots that are already booked
        if not slot.is_available:
            continue
        # Must belong to the requested provider
        if slot.provider_id != provider_id:
            continue
        # Optionally restrict to a specific location
        if location_id is not None and slot.department_id != location_id:
            continue
        # Optionally restrict to a specific appointment duration
        if duration is not None and slot.duration_minutes != duration:
            continue
        # Must fall within the requested date window
        if not (date_from <= slot.start <= date_to):
            continue
        matching.append(slot)

    return matching


# ---------------------------------------------------------------------------
# Pure helper: alternative location fallback
# ---------------------------------------------------------------------------

def _find_alternative_locations(
    slots: dict,
    departments: dict,
    provider_id: int,
    excluded_location_id: int,
    date_from: datetime,
    date_to: datetime,
    duration: Optional[int] = None,
) -> List[dict]:
    """Find the provider's earliest available slot at each of their *other* locations.

    Called only when a location-specific search returns zero results. Returns
    one entry per alternative location (the earliest slot at that location),
    sorted by the next available slot time.

    Args:
        slots:               db["slots"] dict.
        departments:         db["departments"] dict for address/phone lookup.
        provider_id:         The provider being searched.
        excluded_location_id: The location that already returned no results.
        date_from:           Search window start.
        date_to:             Search window end.
        duration:            If given, only consider slots of this duration.

    Returns:
        List of location summary dicts, each containing location_id,
        location_name, address, phone, and next_slot_date/time/id.
        Empty list if the provider has no availability elsewhere.
    """
    # Collect available slots at all OTHER locations within the window
    other_slots = _filter_slots(
        slots, provider_id, date_from, date_to,
        duration=duration,
    )
    # Exclude the location that was already tried
    other_slots = [s for s in other_slots if s.department_id != excluded_location_id]

    if not other_slots:
        return []

    # Sort chronologically so the first entry per location is the earliest slot
    other_slots.sort(key=lambda s: s.start)

    # Build one summary entry per location, using the earliest slot found there
    seen: dict = {}
    for slot in other_slots:
        if slot.department_id in seen:
            continue  # already captured the earliest slot for this location
        dept = departments.get(slot.department_id)
        seen[slot.department_id] = {
            "location_id":    slot.department_id,
            "location_name":  dept.name    if dept else "Unknown",
            "address":        dept.address if dept else "",
            "phone":          dept.phone   if dept else "",
            "next_slot_date": slot.start.strftime("%A, %B %d, %Y"),
            "next_slot_time": slot.start.strftime("%I:%M %p"),
            "next_slot_id":   slot.id,
        }

    return list(seen.values())


# ---------------------------------------------------------------------------
# Pure helper: group slots by day
# ---------------------------------------------------------------------------

def _group_by_day(slots: List, departments: dict) -> dict:
    """Bucket a sorted list of slot objects into a day-keyed dict for the LLM.

    Each key is a human-readable date string ("Monday, April 1, 2026").
    Each value is a list of slot summary dicts (time, duration, location,
    address). Slot IDs are included so the LLM can reference them when
    calling book_appointment, but the system prompt instructs the LLM not
    to display them to the nurse.

    Args:
        slots:       Chronologically sorted slot objects (already capped to
                     MAX_SLOTS_RETURNED by the caller).
        departments: db["departments"] dict for location name/address lookup.

    Returns:
        Ordered dict of {day_label: [slot_dict, …]}.
    """
    grouped: dict = {}
    for slot in slots:
        day_key = slot.start.strftime("%A, %B %d, %Y")
        dept = departments.get(slot.department_id)
        grouped.setdefault(day_key, []).append({
            "slot_id":          slot.id,
            "time":             slot.start.strftime("%I:%M %p"),
            "duration_minutes": slot.duration_minutes,
            "location":         dept.name    if dept else "Unknown",
            "address":          dept.address if dept else "",
        })
    return grouped


# ---------------------------------------------------------------------------
# Tool class — thin composition of the four helpers above
# ---------------------------------------------------------------------------

class FindAvailableSlotsTool(BaseTool):
    name = "find_available_slots"
    description = (
        "Search for available appointment slots for a provider at a given location. "
        "Filter by duration: use 30 for NEW patients, 15 for ESTABLISHED. "
        f"Returns up to {MAX_SLOTS_RETURNED} slots grouped by day. "
        "IMPORTANT: always search the full default window (today → 28 days). "
        "Do NOT narrow the date range to match a time-of-day preference — "
        "filter the returned results instead."
    )
    schema = {
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
                "description": f"End of search window in YYYY-MM-DD format (defaults to {DEFAULT_WINDOW_DAYS} days from today)",
            },
        },
        "required": ["provider_id", "duration"],
    }
    requires_patient_verification = True

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        # --- Coerce inputs ---------------------------------------------------
        provider_id = int(args["provider_id"])
        location_id = int(args["location_id"]) if args.get("location_id") is not None else None
        duration    = int(args["duration"])     if args.get("duration")    is not None else None

        # --- Step 1: Resolve the search date window --------------------------
        # Defaults to today → +28 days; silently ignores malformed ISO strings.
        date_from, date_to = _resolve_date_window(
            args.get("date_from"),
            args.get("date_to"),
        )

        # --- Step 2: Filter the slot dictionary ------------------------------
        # Returns all available slots matching provider / location / duration / window.
        matching = _filter_slots(
            db["slots"], provider_id, date_from, date_to,
            location_id=location_id,
            duration=duration,
        )

        # --- Step 3: Fallback — same provider at other locations -------------
        # Only triggered when a location-specific search returns nothing.
        # Surfaces the provider's next available slot at each alternative site.
        if not matching:
            if location_id is not None:
                alternatives = _find_alternative_locations(
                    db["slots"], db["departments"],
                    provider_id, location_id, date_from, date_to,
                    duration=duration,
                )
                if alternatives:
                    return {
                        "found": False,
                        "message": (
                            "No slots at the requested location, but this provider "
                            "has availability at other locations they practice at."
                        ),
                        "provider_available_at_other_locations": alternatives,
                    }
            return {"found": False, "message": "No available slots found for the given criteria."}

        # --- Step 4: Sort and cap the result set -----------------------------
        # Sort chronologically, then cap at MAX_SLOTS_RETURNED to keep the LLM
        # context window manageable without cutting off entire days arbitrarily.
        matching.sort(key=lambda s: s.start)
        capped = matching[:MAX_SLOTS_RETURNED]

        # --- Step 5: Group by day and format the JSON response ---------------
        # Each day key is "Weekday, Month DD, YYYY"; values are slot summaries.
        grouped = _group_by_day(capped, db["departments"])

        return {
            "found":           True,
            "total_available": len(matching),
            "slots_shown":     len(capped),
            "slots":           grouped,
        }


registry.register(FindAvailableSlotsTool())
