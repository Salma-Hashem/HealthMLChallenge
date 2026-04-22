"""
Slot generator for the Care Coordinator Assistant.

Generates available appointment slots for each provider at each of their
departments for a configurable window (default 14 days, production uses 28),
respecting office hours and using a deterministic hash to mark ~80% of
slots as available.
"""

import hashlib
from datetime import date, datetime, timedelta
from typing import Dict, Optional

from core.models import Department, Provider, Slot


def _deterministic_available(slot_id: str) -> bool:
    """~80% of slots are available, determined by a stable hash."""
    digest = int(hashlib.md5(slot_id.encode()).hexdigest(), 16)
    return digest % 5 != 0


def generate_slots(
    providers: Dict[int, Provider],
    departments: Dict[int, Department],
    start_date: Optional[date] = None,
    num_days: int = 14,
) -> Dict[str, Slot]:
    """Generate realistic appointment slots for the next *num_days*.

    Pattern per hour: one 30-min slot then two 15-min slots (fills 60 min).
    Skips weekends and days before today.
    """
    if start_date is None:
        start_date = date.today()

    slots: Dict[str, Slot] = {}

    for provider in providers.values():
        for dept in provider.departments:
            for day_offset in range(num_days):
                current_date = start_date + timedelta(days=day_offset)

                if current_date.weekday() >= 5:  # Saturday / Sunday
                    continue
                if current_date < date.today():
                    continue

                day_hours = None
                for oh in dept.hours:
                    if oh.day_of_week == current_date.weekday():
                        day_hours = oh
                        break

                if day_hours is None:
                    continue

                cursor = datetime.combine(current_date, day_hours.open_time)
                end_of_day = datetime.combine(current_date, day_hours.close_time)

                slot_counter = 0
                while cursor < end_of_day:
                    duration = 30 if slot_counter % 3 == 0 else 15
                    slot_end = cursor + timedelta(minutes=duration)
                    if slot_end > end_of_day:
                        break

                    slot_id = (
                        f"slot-{provider.id}-{dept.id}"
                        f"-{current_date.isoformat()}"
                        f"-{cursor.strftime('%H%M')}"
                    )

                    slots[slot_id] = Slot(
                        id=slot_id,
                        provider_id=provider.id,
                        department_id=dept.id,
                        start=cursor,
                        end=slot_end,
                        duration_minutes=duration,
                        is_available=_deterministic_available(slot_id),
                    )

                    cursor = slot_end
                    slot_counter += 1

    return slots
