"""
Data models for the Care Coordinator Assistant.

Defines Pydantic v2 BaseModel classes for all core entities: providers,
patients, appointments, slots, insurance, and booking requests/confirmations.

  - Pydantic validates types on construction (LLM sending "abc" for an int
    field raises ValidationError immediately instead of failing silently later).
  - model_json_schema() auto-generates OpenAI-compatible JSON Schema from the
    same type annotations used at runtime — single source of truth.
"""

import datetime as dt
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_serializer


_DAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


class OfficeHours(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Monday … 6=Sunday")
    open_time: dt.time
    close_time: dt.time

    # Serialize internal fields into a user-friendly format
    @model_serializer
    def serialize(self) -> dict:
        """Produce the established {day, open, close} shape used by every caller."""
        return {
            "day": _DAY_NAMES[self.day_of_week],
            "open": self.open_time.strftime("%H:%M"),
            "close": self.close_time.strftime("%H:%M"),
        }


class Department(BaseModel):
    id: int
    name: str
    phone: str
    address: str
    hours: List[OfficeHours] = Field(default_factory=list)


class Provider(BaseModel):
    id: int
    last_name: str
    first_name: str
    certification: str
    specialty: str
    departments: List[Department] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def display_name(self) -> str:
        return f"Dr. {self.first_name} {self.last_name}"


class ReferredProvider(BaseModel):
    specialty: str
    provider_name: Optional[str] = None
    provider_id: Optional[int] = None


class Patient(BaseModel):
    id: int
    first_name: str
    last_name: str
    dob: dt.date
    pcp: str
    ehr_id: str
    referred_providers: List[ReferredProvider] = Field(default_factory=list)
    insurance: Optional[str] = None


class Appointment(BaseModel):
    """A scheduled or historical patient appointment."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int
    patient_id: int
    provider_id: int
    date: dt.date
    time: dt.time
    status: str  # completed or noshow or cancelled or booked
    confirmation_number: Optional[str] = None
    appointment_type: Optional[str] = None  # NEW or ESTABLISHED
    reason: Optional[str] = None


class Slot(BaseModel):
    """An available (or already-booked) time slot for a provider."""

    id: str
    provider_id: int
    department_id: int
    start: dt.datetime
    end: dt.datetime
    duration_minutes: int
    is_available: bool = True


class InsuranceInfo(BaseModel):
    accepted_plans: List[str] = Field(default_factory=list)
    self_pay_rates: dict = Field(default_factory=dict)


class InsurancePlan(BaseModel):
    name: str
    accepted: bool


class SelfPayRate(BaseModel):
    specialty: str
    amount: float


class BookingRequest(BaseModel):
    patient_id: int = Field(description="Patient ID from verify_patient")
    slot_id: str = Field(description="Slot ID from find_available_slots")
    appointment_type: Literal["NEW", "ESTABLISHED"] = Field(
        description="NEW if first visit or >5 years ago, ESTABLISHED otherwise"
    )
    reason: str = Field(default="", description="Optional reason for the visit")


class BookingConfirmation(BaseModel):
    confirmation_number: str
    patient_name: str
    provider_name: str
    location: str
    appt_datetime: dt.datetime
    type: str
    arrival_instructions: str
