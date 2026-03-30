"""
Tool: find_available_slots

Searches for available appointment slots for a provider, optionally filtered
by location and duration. When a specific location has no slots, automatically
checks the provider's other locations and surfaces them.
"""

from datetime import date, datetime, timedelta

from tools.base import BaseTool
from tools.registry import registry


class FindAvailableSlotsTool(BaseTool):
    name = "find_available_slots"
    description = (
        "Search for available appointment slots for a provider at a given location. "
        "Filter by duration: use 30 for NEW patients, 15 for ESTABLISHED. "
        "Returns up to 40 slots grouped by day. "
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
                "description": "End of search window in YYYY-MM-DD format (defaults to 28 days from today)",
            },
        },
        "required": ["provider_id", "duration"],
    }
    requires_patient_verification = True

    def execute(self, args: dict, db: dict, session: dict) -> dict:
        provider_id = int(args["provider_id"])
        location_id = int(args["location_id"]) if args.get("location_id") is not None else None
        duration = args.get("duration")

        today = date.today()
        date_from = datetime.combine(today, datetime.min.time())
        date_to = datetime.combine(
            today + timedelta(days=28),
            datetime.max.time().replace(microsecond=0),
        )

        if args.get("date_from"):
            date_from = datetime.fromisoformat(args["date_from"])
        if args.get("date_to"):
            date_to = datetime.fromisoformat(args["date_to"])

        matching = [
            s for s in db["slots"].values()
            if s.is_available
            and s.provider_id == provider_id
            and (location_id is None or s.department_id == location_id)
            and (duration is None or s.duration_minutes == int(duration))
            and date_from <= s.start <= date_to
        ]

        if not matching:
            return self._no_slots_response(
                provider_id, location_id, duration, date_from, date_to, db
            )

        matching.sort(key=lambda s: s.start)
        grouped: dict = {}
        for slot in matching[:40]:
            day_key = slot.start.strftime("%A, %B %d, %Y")
            dept = db["departments"].get(slot.department_id)
            grouped.setdefault(day_key, []).append({
                "slot_id": slot.id,
                "time": slot.start.strftime("%I:%M %p"),
                "duration_minutes": slot.duration_minutes,
                "location": dept.name if dept else "Unknown",
                "address": dept.address if dept else "",
            })

        return {
            "found": True,
            "total_available": len(matching),
            "slots_shown": min(40, len(matching)),
            "slots": grouped,
        }

    def _no_slots_response(
        self, provider_id, location_id, duration, date_from, date_to, db
    ) -> dict:
        """When no slots match, check if the provider has availability elsewhere."""
        if location_id is None:
            return {"found": False, "message": "No available slots found for the given criteria."}

        other = [
            s for s in db["slots"].values()
            if s.is_available
            and s.provider_id == provider_id
            and s.department_id != location_id
            and (duration is None or s.duration_minutes == int(duration))
            and date_from <= s.start <= date_to
        ]
        if not other:
            return {"found": False, "message": "No available slots found for the given criteria."}

        other.sort(key=lambda s: s.start)
        seen_locs: dict = {}
        for s in other:
            if s.department_id not in seen_locs:
                dept = db["departments"].get(s.department_id)
                seen_locs[s.department_id] = {
                    "location_id": s.department_id,
                    "location_name": dept.name if dept else "Unknown",
                    "address": dept.address if dept else "",
                    "phone": dept.phone if dept else "",
                    "next_slot_date": s.start.strftime("%A, %B %d, %Y"),
                    "next_slot_time": s.start.strftime("%I:%M %p"),
                    "next_slot_id": s.id,
                }

        return {
            "found": False,
            "message": (
                "No slots at the requested location, but this provider has "
                "availability at other locations they practice at."
            ),
            "provider_available_at_other_locations": list(seen_locs.values()),
        }


registry.register(FindAvailableSlotsTool())
