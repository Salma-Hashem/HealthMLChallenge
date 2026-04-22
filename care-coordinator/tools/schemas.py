"""
Pydantic v2 input models for every Care Coordinator tool.

These Pydantic models are the single source of truth.  One change here
propagates automatically to:
  1. The Cerebras/OpenAI tool schema sent to the LLM
     (graph.py calls model_json_schema() via schema_for() in each tool class)
  2. LangChain StructuredTool stubs in graph.py
     (args_schema= parameter drives llm.bind_tools())
  3. Runtime documentation — Field(description=...) is what the LLM reads
     when deciding how to populate each argument.

schema_for(model) strips Pydantic's top-level "title" key before the dict
is handed to the tool registry, matching the shape the OpenAI API expects.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


def schema_for(model: type) -> dict:
    """Return model_json_schema() with the top-level 'title' removed."""
    s = model.model_json_schema()
    s.pop("title", None)
    return s


# ---------------------------------------------------------------------------
# Patient tools
# ---------------------------------------------------------------------------

class VerifyPatientArgs(BaseModel):
    """Search for a patient by name and/or date of birth to verify identity."""

    first_name: str = Field(
        default="",
        description="Patient's first name (partial match supported)",
    )
    last_name: str = Field(
        default="",
        description="Patient's last name (partial match supported)",
    )
    dob: str = Field(
        default="",
        description="Date of birth in YYYY-MM-DD format (e.g. '1975-01-01')",
    )


class LookupProviderArgs(BaseModel):
    """Find providers by name, specialty, or location."""

    name: str = Field(
        default="",
        description="Provider last name or full name (e.g. 'House' or 'Gregory House')",
    )
    specialty: str = Field(
        default="",
        description="Medical specialty (e.g. 'Orthopedics', 'Primary Care', 'Surgery')",
    )
    location: str = Field(
        default="",
        description="Hospital or clinic name to filter by (e.g. 'Jefferson Hospital', 'PPTH')",
    )


# ---------------------------------------------------------------------------
# Scheduling tools
# ---------------------------------------------------------------------------

class GetBookingHistoryArgs(BaseModel):
    """Check whether a patient has seen a specific provider before."""

    patient_id: int = Field(description="Patient ID returned by verify_patient")
    provider_id: int = Field(description="Provider ID returned by lookup_provider_info")


class FindAvailableSlotsArgs(BaseModel):
    """Search for available appointment slots for a provider."""

    provider_id: int = Field(description="Provider ID")
    duration: Literal[15, 30] = Field(
        description="Required slot duration in minutes: 30 for NEW, 15 for ESTABLISHED"
    )
    location_id: Optional[int] = Field(
        default=None,
        description="Department/location ID (omit to search all locations for this provider)",
    )
    date_from: Optional[str] = Field(
        default=None,
        description="Start of search window in YYYY-MM-DD format (defaults to today)",
    )
    date_to: Optional[str] = Field(
        default=None,
        description="End of search window in YYYY-MM-DD format (defaults to 28 days from today)",
    )


class CheckProviderAvailabilityArgs(BaseModel):
    """Get a provider's full profile including all departments and office hours."""

    provider_id: int = Field(description="Provider ID")


class ListAlternativeProvidersArgs(BaseModel):
    """Find other providers in the same specialty."""

    specialty: str = Field(
        description="Medical specialty (e.g. 'Orthopedics', 'Primary Care')"
    )
    exclude_provider_id: Optional[int] = Field(
        default=None,
        description="Provider ID to exclude (the unavailable provider)",
    )
    patient_id: Optional[int] = Field(
        default=None,
        description=(
            "Patient ID — when provided, includes whether the patient has "
            "seen each alternative provider before"
        ),
    )
    duration: Optional[Literal[15, 30]] = Field(
        default=None,
        description="Slot duration in minutes (15 or 30) — when provided, returns next available slots per provider",
    )


class BookAppointmentArgs(BaseModel):
    """Finalise an appointment booking after explicit nurse confirmation."""

    patient_id: int = Field(description="Patient ID from verify_patient")
    slot_id: str = Field(description="Slot ID from find_available_slots")
    appointment_type: Literal["NEW", "ESTABLISHED"] = Field(
        description="Appointment type from get_booking_history: 'NEW' or 'ESTABLISHED'"
    )
    reason: str = Field(
        default="",
        description="Brief reason for the visit (e.g. 'Orthopedics referral post-discharge')",
    )


# ---------------------------------------------------------------------------
# Insurance tools
# ---------------------------------------------------------------------------

class VerifyInsuranceArgs(BaseModel):
    """Check whether a patient's insurance plan is accepted."""

    plan_name: str = Field(
        description=(
            "Insurance plan name as stated by the nurse "
            "(e.g. 'BCBS', 'Blue Cross Blue Shield of NC', 'Aetna', 'Cigna')"
        )
    )


class GetSelfpayRateArgs(BaseModel):
    """Get the self-pay cost for a medical specialty."""

    specialty: str = Field(
        description="Medical specialty (e.g. 'Orthopedics', 'Primary Care', 'Surgery')"
    )
