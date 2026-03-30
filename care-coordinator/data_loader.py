"""
Data loader for the Care Coordinator Assistant.

Parses data_sheet.txt into structured in-memory data: providers, departments,
insurance plans, self-pay rates, and seeds the John Doe test patient.

parse_providers is split into two phases:
  Phase 1 — _extract_provider_blocks(lines)
      Reads raw lines and segments them into per-provider line groups.
      No object construction happens here — only text segmentation.
      The trailing-save footgun disappears because blocks are complete
      before Phase 2 ever sees them.

  Phase 2 — _build_provider(block, provider_id, start_dept_id)
      Constructs a Provider dataclass from an already-isolated block.
      Each phase can be unit-tested independently with a few fabricated
      lines rather than a full file.
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

# Section header / terminator strings (lowercased for case-insensitive matching).
_SECTION_HEADER     = "provider directory"
_SECTION_TERMINATOR = "appointments:"


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


def parse_hours_string(hours_str: str) -> List[OfficeHours]:
    """Parse 'M-F 9am-5pm', 'Tu-Th 10am-4pm', etc."""
    hours_str = hours_str.strip()
    match = re.match(
        r"([A-Za-z]+)-([A-Za-z]+)\s+(\d{1,2}(?:am|pm))-(\d{1,2}(?:am|pm))",
        hours_str,
    )
    if not match:
        raise ValueError(f"Cannot parse hours: {hours_str}")

    start_day_abbr = match.group(1)
    end_day_abbr   = match.group(2)
    open_time      = parse_time_str(match.group(3))
    close_time     = parse_time_str(match.group(4))

    start_idx = DAY_ABBREV_TO_INT.get(start_day_abbr)
    end_idx   = DAY_ABBREV_TO_INT.get(end_day_abbr)

    if start_idx is None or end_idx is None:
        raise ValueError(f"Unknown day abbreviation in: {hours_str}")

    return [
        OfficeHours(day_of_week=i, open_time=open_time, close_time=close_time)
        for i in range(start_idx, end_idx + 1)
    ]


# ---------------------------------------------------------------------------
# Phase 1 — Segmentation
# ---------------------------------------------------------------------------

# Regex that identifies a provider name header line ("- Grey, Meredith" or
# "Brennan, Temperance").  Matching this pattern is the only seam between
# providers in the flat text format.
_PROVIDER_HEADER_RE = re.compile(r"^-?\s*([A-Za-z]+),\s+([A-Za-z]+)\s*$")


def _extract_provider_blocks(lines: List[str]) -> List[List[str]]:
    """Phase 1: Segment raw lines into per-provider line groups.

    Scans the input for the "Provider Directory" section header, then
    accumulates lines into a block until a new provider header line is
    detected (or the "Appointments:" section terminator is reached).

    Each returned block is a list of stripped, non-empty lines where:
      - block[0]  is always the "Last, First" provider header line.
      - block[1:] are the attribute lines for that provider
                  (certification, specialty, departments, …).

    No dataclass objects are constructed here.  The trailing-save problem
    from the old single-pass approach is avoided because blocks are closed
    when the *next* provider header is seen, not at end-of-loop.

    Robustness improvements over the old implementation:
      - Section header matching is case-insensitive and strips surrounding
        whitespace, so "  Provider Directory  " still works.
      - Empty lines inside the section are skipped without breaking state.

    Args:
        lines: Raw lines from the data sheet (may include newline chars).

    Returns:
        Ordered list of line groups, one per provider found in the section.
    """
    blocks: List[List[str]] = []
    current_block: List[str] = []
    in_section = False

    for raw_line in lines:
        stripped = raw_line.strip()

        # --- Detect section start (case-insensitive) ----------------------
        if stripped.lower() == _SECTION_HEADER:
            in_section = True
            continue

        # --- Detect section end -------------------------------------------
        if in_section and stripped.lower().startswith(_SECTION_TERMINATOR):
            break

        # --- Skip lines outside the section or blank lines within it ------
        if not in_section or not stripped:
            continue

        # --- Detect a new provider header line ----------------------------
        # When we find a new header, the current block (if any) is complete —
        # save it before starting a fresh block for the new provider.
        if _PROVIDER_HEADER_RE.match(stripped):
            if current_block:
                blocks.append(current_block)
            current_block = [stripped]
            continue

        # --- Accumulate attribute lines for the current provider ----------
        if current_block:
            current_block.append(stripped)

    # Capture the final block.  This is the only "trailing save" in the
    # whole parser and it is intentional and obvious: after the loop there
    # may be one block that was never closed by a following provider header.
    if current_block:
        blocks.append(current_block)

    return blocks


# ---------------------------------------------------------------------------
# Phase 2 — Object construction
# ---------------------------------------------------------------------------

def _build_provider(
    block: List[str],
    provider_id: int,
    start_dept_id: int,
) -> Tuple[Provider, int]:
    """Phase 2: Construct a Provider dataclass from an isolated line block.

    Receives the output of _extract_provider_blocks for a single provider
    (block[0] is the "Last, First" header; block[1:] are attribute lines).
    No file I/O or section scanning happens here.

    Department lines accumulate into a running Department object.  Each
    "department:" marker closes the previous department and opens a new one.
    The final department is saved before the function returns — this is the
    only trailing save, and it is local and visible, not buried at the end
    of a 90-line loop.

    Args:
        block:          Lines for one provider from _extract_provider_blocks.
        provider_id:    ID to assign to this Provider.
        start_dept_id:  The dept_id counter value before processing this block.
                        Departments are numbered sequentially across all providers.

    Returns:
        (provider, next_dept_id) — the constructed Provider and the updated
        dept_id counter for the next call.
    """
    # --- Parse the provider name from the header line ---------------------
    header_match = _PROVIDER_HEADER_RE.match(block[0])
    provider = Provider(
        id=provider_id,
        last_name=header_match.group(1),
        first_name=header_match.group(2),
        certification="",
        specialty="",
        departments=[],
    )

    current_dept: Optional[Department] = None
    dept_id = start_dept_id

    # --- Process attribute lines ------------------------------------------
    for line in block[1:]:

        # certification: MD
        cert_match = re.match(r"^-?\s*certification:\s*(.+)$", line)
        if cert_match:
            provider.certification = cert_match.group(1).strip()
            continue

        # specialty: Orthopedics
        spec_match = re.match(r"^-?\s*specialty:\s*(.+)$", line)
        if spec_match:
            provider.specialty = spec_match.group(1).strip()
            continue

        # department: (marker line — no value on this line)
        if re.match(r"^-?\s*department:\s*$", line):
            # Close the previous department before opening a new one
            if current_dept is not None:
                provider.departments.append(current_dept)
            dept_id += 1
            current_dept = Department(id=dept_id, name="", phone="", address="", hours=[])
            continue

        # Department field lines (only valid while a department is open)
        if current_dept is not None:
            name_match = re.match(r"^-?\s*name:\s*(.+)$", line)
            if name_match:
                current_dept.name = name_match.group(1).strip()
                continue

            phone_match = re.match(r"^-?\s*phone:\s*(.+)$", line)
            if phone_match:
                current_dept.phone = phone_match.group(1).strip()
                continue

            addr_match = re.match(r"^-?\s*address:\s*(.+)$", line)
            if addr_match:
                current_dept.address = addr_match.group(1).strip()
                continue

            hours_match = re.match(r"^-?\s*hours:\s*(.+)$", line)
            if hours_match:
                current_dept.hours = parse_hours_string(hours_match.group(1))
                continue

    # Save the last open department (local and obvious — not a global footgun)
    if current_dept is not None:
        provider.departments.append(current_dept)

    return provider, dept_id


# ---------------------------------------------------------------------------
# Public entry point — composes Phase 1 + Phase 2
# ---------------------------------------------------------------------------

def parse_providers(lines: List[str]) -> List[Provider]:
    """Parse the Provider Directory section into a list of Provider objects.

    Two-phase approach:
      1. _extract_provider_blocks  segments lines into raw per-provider groups.
      2. _build_provider           constructs each Provider from its group.

    The public signature is unchanged from the original implementation.
    """
    # Phase 1: segment — pure text, no objects
    blocks = _extract_provider_blocks(lines)

    # Phase 2: construct — pure object building, no text scanning
    providers: List[Provider] = []
    provider_id = 0
    dept_id = 0
    for block in blocks:
        provider_id += 1
        provider, dept_id = _build_provider(block, provider_id, dept_id)
        providers.append(provider)

    return providers


# ---------------------------------------------------------------------------
# Remaining parsers (unchanged)
# ---------------------------------------------------------------------------

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

    providers       = parse_providers(lines)
    accepted_plans  = parse_insurance(lines)
    self_pay_rates  = parse_self_pay(lines)
    patients, appointments = load_patient_data()

    insurance_info = InsuranceInfo(
        accepted_plans=accepted_plans,
        self_pay_rates=self_pay_rates,
    )

    return {
        "providers":    {p.id: p for p in providers},
        "patients":     {p.id: p for p in patients},
        "appointments": appointments,
        "insurance":    insurance_info,
        "departments":  {d.id: d for p in providers for d in p.departments},
    }
