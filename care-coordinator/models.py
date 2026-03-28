"""
Data models for the Care Coordinator Assistant.

Defines dataclasses for all core entities: providers, patients, appointments,
slots, insurance, and booking requests/confirmations.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional


_DAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


@dataclass
class OfficeHours:
    day_of_week: int  # 0=Monday ... 6=Sunday
    open_time: dt.time
    close_time: dt.time

    def to_dict(self) -> dict:
        return {
            "day": _DAY_NAMES[self.day_of_week],
            "open": self.open_time.strftime("%H:%M"),
            "close": self.close_time.strftime("%H:%M"),
        }


@dataclass
class Department:
    id: int
    name: str
    phone: str
    address: str
    hours: list = field(default_factory=list)  # list[OfficeHours]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "address": self.address,
            "hours": [oh.to_dict() for oh in self.hours],
        }


@dataclass
class Provider:
    id: int
    last_name: str
    first_name: str
    certification: str
    specialty: str
    departments: list = field(default_factory=list)  # list[Department]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def display_name(self) -> str:
        return f"Dr. {self.first_name} {self.last_name}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "certification": self.certification,
            "specialty": self.specialty,
            "departments": [d.to_dict() for d in self.departments],
        }


@dataclass
class ReferredProvider:
    specialty: str
    provider_name: Optional[str] = None
    provider_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "specialty": self.specialty,
            "provider_name": self.provider_name,
            "provider_id": self.provider_id,
        }


@dataclass
class Patient:
    id: int
    first_name: str
    last_name: str
    dob: dt.date
    pcp: str
    ehr_id: str
    referred_providers: list = field(default_factory=list)  # list[ReferredProvider]
    insurance: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "dob": self.dob.isoformat(),
            "pcp": self.pcp,
            "ehr_id": self.ehr_id,
            "referred_providers": [r.to_dict() for r in self.referred_providers],
            "insurance": self.insurance,
        }


@dataclass
class Appointment:
    id: int
    patient_id: int
    provider_id: int
    date: dt.date
    time: dt.time
    status: str  # completed, noshow, cancelled, booked
    confirmation_number: Optional[str] = None
    appointment_type: Optional[str] = None  # NEW or ESTABLISHED
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "provider_id": self.provider_id,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M"),
            "status": self.status,
            "confirmation_number": self.confirmation_number,
            "appointment_type": self.appointment_type,
            "reason": self.reason,
        }


@dataclass
class Slot:
    id: str
    provider_id: int
    department_id: int
    start: dt.datetime
    end: dt.datetime
    duration_minutes: int
    is_available: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "department_id": self.department_id,
            "location_id": self.department_id,  # alias per spec
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "is_available": self.is_available,
        }


@dataclass
class InsuranceInfo:
    accepted_plans: list = field(default_factory=list)   # list[str]
    self_pay_rates: dict = field(default_factory=dict)   # dict[str, float]

    def to_dict(self) -> dict:
        return {
            "accepted_plans": self.accepted_plans,
            "self_pay_rates": self.self_pay_rates,
        }


@dataclass
class InsurancePlan:
    name: str
    accepted: bool

    def to_dict(self) -> dict:
        return {"name": self.name, "accepted": self.accepted}


@dataclass
class SelfPayRate:
    specialty: str
    amount: float

    def to_dict(self) -> dict:
        return {"specialty": self.specialty, "amount": self.amount}


@dataclass
class BookingRequest:
    patient_id: int
    slot_id: str
    appointment_type: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "slot_id": self.slot_id,
            "appointment_type": self.appointment_type,
            "reason": self.reason,
        }


@dataclass
class BookingConfirmation:
    confirmation_number: str
    patient_name: str
    provider_name: str
    location: str
    appt_datetime: dt.datetime
    type: str
    arrival_instructions: str

    def to_dict(self) -> dict:
        return {
            "confirmation_number": self.confirmation_number,
            "patient_name": self.patient_name,
            "provider_name": self.provider_name,
            "location": self.location,
            "datetime": self.appt_datetime.isoformat(),
            "type": self.type,
            "arrival_instructions": self.arrival_instructions,
        }
