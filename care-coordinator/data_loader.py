"""
Data loader for the Care Coordinator Assistant.

Parses data_sheet.txt into structured in-memory data: providers, departments,
insurance plans, self-pay rates, and seeds the John Doe test patient.
"""

import re
from datetime import date, time
from typing import Dict, List, Optional, Tuple

from models import (
    Provider, Department, OfficeHours, Patient, ReferredProvider,
    Appointment, InsuranceInfo,
)

DAY_ABBREV_ORDER = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]
DAY_ABBREV_TO_INT = {abbr: i for i, abbr in enumerate(DAY_ABBREV_ORDER)}


def parse_time_str(t: str) -> time:
    """Parse '9am', '5pm', '10am', '4pm' into a time object."""
    t = t.strip().lower()
    match = re.match(r"(\d{1,2})(am|pm)", t)
    if not match:
        raise ValueError(f"Cannot parse time: {t}")
    hour = int(match.group(1))
    ampm = match.group(2)
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return time(hour, 0)


def parse_hours_string(hours_str: str) -> list[OfficeHours]:
    """Parse 'M-F 9am-5pm', 'Tu-Th 10am-4pm', etc."""
    hours_str = hours_str.strip()
    match = re.match(
        r"([A-Za-z]+)-([A-Za-z]+)\s+(\d{1,2}(?:am|pm))-(\d{1,2}(?:am|pm))",
        hours_str,
    )
    if not match:
        raise ValueError(f"Cannot parse hours: {hours_str}")

    start_day_abbr = match.group(1)
    end_day_abbr = match.group(2)
    open_time = parse_time_str(match.group(3))
    close_time = parse_time_str(match.group(4))

    start_idx = DAY_ABBREV_TO_INT.get(start_day_abbr)
    end_idx = DAY_ABBREV_TO_INT.get(end_day_abbr)

    if start_idx is None or end_idx is None:
        raise ValueError(f"Unknown day abbreviation in: {hours_str}")

    return [
        OfficeHours(day_of_week=i, open_time=open_time, close_time=close_time)
        for i in range(start_idx, end_idx + 1)
    ]


def parse_providers(lines: List[str]) -> List[Provider]:
    """Parse the Provider Directory section."""
    providers: List[Provider] = []
    provider_id = 0
    dept_id = 0
    current_provider: Optional[Provider] = None
    current_dept: Optional[Department] = None
    in_provider_section = False

    for raw_line in lines:
        stripped = raw_line.strip()

        if stripped == "Provider Directory":
            in_provider_section = True
            continue

        if stripped.startswith("Appointments:"):
            break

        if not in_provider_section or not stripped:
            continue

        # New provider: "- Grey, Meredith" or "Brennan, Temperance"
        provider_match = re.match(r"^-?\s*([A-Za-z]+),\s+([A-Za-z]+)\s*$", stripped)
        if provider_match:
            if current_dept and current_provider:
                current_provider.departments.append(current_dept)
                current_dept = None
            if current_provider:
                providers.append(current_provider)

            provider_id += 1
            current_provider = Provider(
                id=provider_id,
                last_name=provider_match.group(1),
                first_name=provider_match.group(2),
                certification="",
                specialty="",
                departments=[],
            )
            current_dept = None
            continue

        if current_provider is None:
            continue

        cert_match = re.match(r"^-?\s*certification:\s*(.+)$", stripped)
        if cert_match:
            current_provider.certification = cert_match.group(1).strip()
            continue

        spec_match = re.match(r"^-?\s*specialty:\s*(.+)$", stripped)
        if spec_match:
            current_provider.specialty = spec_match.group(1).strip()
            continue

        if re.match(r"^-?\s*department:\s*$", stripped):
            if current_dept:
                current_provider.departments.append(current_dept)
            dept_id += 1
            current_dept = Department(
                id=dept_id, name="", phone="", address="", hours=[]
            )
            continue

        if current_dept is not None:
            name_match = re.match(r"^-?\s*name:\s*(.+)$", stripped)
            if name_match:
                current_dept.name = name_match.group(1).strip()
                continue
            phone_match = re.match(r"^-?\s*phone:\s*(.+)$", stripped)
            if phone_match:
                current_dept.phone = phone_match.group(1).strip()
                continue
            addr_match = re.match(r"^-?\s*address:\s*(.+)$", stripped)
            if addr_match:
                current_dept.address = addr_match.group(1).strip()
                continue
            hours_match = re.match(r"^-?\s*hours:\s*(.+)$", stripped)
            if hours_match:
                current_dept.hours = parse_hours_string(hours_match.group(1))
                continue

    # Save trailing provider/department
    if current_dept and current_provider:
        current_provider.departments.append(current_dept)
    if current_provider and (not providers or providers[-1] is not current_provider):
        providers.append(current_provider)

    return providers


def parse_insurance(lines: List[str]) -> List[str]:
    """Parse accepted insurance plans."""
    plans: List[str] = []
    in_section = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped == "Accepted Insurances:":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                plans.append(stripped[2:].strip())
            elif stripped == "":
                continue
            else:
                break
    return plans


def parse_self_pay(lines: List[str]) -> Dict[str, float]:
    """Parse self-pay rates by specialty."""
    rates: Dict[str, float] = {}
    in_section = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped == "Self-pay:":
            in_section = True
            continue
        if in_section:
            match = re.match(r"^-\s*(.+?):\s*\$(\d+)", stripped)
            if match:
                rates[match.group(1).strip()] = float(match.group(2))
            elif stripped and not stripped.startswith("-"):
                break
    return rates


def load_patient_data() -> Tuple[List[Patient], List[Appointment]]:
    """Seed John Doe patient record and appointment history."""
    patient = Patient(
        id=1,
        first_name="John",
        last_name="Doe",
        dob=date(1975, 1, 1),
        pcp="Dr. Meredith Grey",
        ehr_id="1234abcd",
        referred_providers=[
            ReferredProvider(
                provider_name="House, Gregory MD",
                specialty="Orthopedics",
                provider_id=2,
            ),
            ReferredProvider(specialty="Primary Care"),
        ],
        insurance="Blue Cross Blue Shield of North Carolina",
    )

    appointments = [
        Appointment(
            id=1, patient_id=1, provider_id=1,
            date=date(2018, 3, 5), time=time(9, 15),
            status="completed",
        ),
        Appointment(
            id=2, patient_id=1, provider_id=2,
            date=date(2024, 8, 12), time=time(14, 30),
            status="completed",
        ),
        Appointment(
            id=3, patient_id=1, provider_id=1,
            date=date(2024, 9, 17), time=time(10, 0),
            status="noshow",
        ),
        Appointment(
            id=4, patient_id=1, provider_id=1,
            date=date(2024, 11, 25), time=time(11, 30),
            status="cancelled",
        ),
    ]

    return [patient], appointments


def load_all_data(data_sheet_path: str) -> dict:
    """Load and return all structured data from the data sheet and seed records."""
    with open(data_sheet_path, "r") as f:
        lines = f.readlines()

    providers = parse_providers(lines)
    accepted_plans = parse_insurance(lines)
    self_pay_rates = parse_self_pay(lines)
    patients, appointments = load_patient_data()

    insurance_info = InsuranceInfo(
        accepted_plans=accepted_plans,
        self_pay_rates=self_pay_rates,
    )

    return {
        "providers": {p.id: p for p in providers},
        "patients": {p.id: p for p in patients},
        "appointments": appointments,
        "insurance": insurance_info,
        "departments": {d.id: d for p in providers for d in p.departments},
    }
