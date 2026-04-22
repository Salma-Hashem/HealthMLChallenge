"""
Guardrails for the Care Coordinator Assistant.

Input guardrails: prompt-injection screening, max-length enforcement.
Output guardrails: PHI pattern detection, medical-advice detection,
                  booking confirmation cross-check, disclaimer injection.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MESSAGE_LENGTH = 2000

# Regex patterns that indicate prompt-injection attempts.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions",  re.compile(r"ignore\s+(all\s+)?(previous|your|the|prior)\s+instructions", re.I)),
    ("new_instructions",     re.compile(r"(your\s+new\s+instructions|new\s+instructions\s+are)", re.I)),
    ("you_are_now",          re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I)),
    ("forget_everything",    re.compile(r"forget\s+(everything|your|all)", re.I)),
    ("act_as",               re.compile(r"act\s+as\s+(a|an)\s+", re.I)),
    ("pretend_to_be",        re.compile(r"pretend\s+(you\s+are|to\s+be)", re.I)),
    ("jailbreak",            re.compile(r"\bjailbreak\b", re.I)),
    ("system_prompt_leak",   re.compile(r"(print|reveal|show|repeat|output)\s+(your\s+)?(system\s+prompt|instructions)", re.I)),
    ("role_override",        re.compile(r"(you\s+are|you're)\s+(now\s+)?(a\s+)?(DAN|evil|unrestricted|uncensored)", re.I)),
    ("prompt_injection_tag", re.compile(r"(\[INST\]|\[SYSTEM\]|<\|system\|>|<\|user\|>)", re.I)),
    ("script_injection",     re.compile(r"<\s*script", re.I)),
    ("override_persona",     re.compile(r"(override|bypass|disable)\s+(your\s+)?(safety|guardrails?|filters?|restrictions?)", re.I)),
]

# Patterns that indicate PHI leakage in output.
_SSN_PATTERN     = re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b")
_MRN_PATTERN     = re.compile(r"\bMRN[\s:#-]*\d{4,}\b", re.I)
_FULL_DOB_IN_OUT = re.compile(r"\bdate[\s_-]?of[\s_-]?birth[\s:]+\d{4}-\d{2}-\d{2}\b", re.I)

# Patterns that indicate the model is giving medical advice.
_MEDICAL_ADVICE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("dosage_advice",       re.compile(r"\btake\s+\d+\s*(mg|mcg|ml|units?)\b", re.I)),
    ("prescription",        re.compile(r"\b(prescribe|prescription|prescribing)\b", re.I)),
    ("diagnosis",           re.compile(r"\byour\s+diagnosis\s+(is|shows?|indicates?)\b", re.I)),
    ("treatment_recommend", re.compile(r"\b(I\s+recommend|you\s+should)\s+(take|start|stop|discontinue)\s+\w+", re.I)),
    ("stop_medication",     re.compile(r"\b(stop|discontinue|cease)\s+taking\s+\w+", re.I)),
]

# Disclaimer appended to flagged output.
_DISCLAIMER = (
    "\n\n---\n"
    "_Note: This response has been reviewed. "
    "For any clinical decisions, please consult the appropriate clinical staff._"
)


# ---------------------------------------------------------------------------
# Public API — Input
# ---------------------------------------------------------------------------

class InputBlocked(Exception):
    """Raised when a user message fails input screening."""
    def __init__(self, reason: str, pattern_key: Optional[str] = None):
        self.reason = reason
        self.pattern_key = pattern_key
        super().__init__(reason)


def check_input(message: str, session_id: str) -> None:
    """
    Screen a user message for injection attempts and length violations.

    Raises InputBlocked if the message should not be processed.
    Callers are responsible for logging via audit_log.
    """
    if len(message) > MAX_MESSAGE_LENGTH:
        raise InputBlocked(
            f"Message exceeds maximum length of {MAX_MESSAGE_LENGTH} characters.",
            "max_length",
        )

    for key, pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            raise InputBlocked(
                f"Potential prompt-injection pattern detected ({key}).",
                key,
            )


def friendly_blocked_message() -> str:
    """Return the user-facing message shown when input is blocked."""
    return (
        "I can only help with healthcare appointment scheduling tasks. "
        "If you have a referral or booking request, please let me know "
        "the patient name and the provider you'd like to book with."
    )


# ---------------------------------------------------------------------------
# Public API — Output
# ---------------------------------------------------------------------------

class OutputFlag:
    """Holds the result of an output scan."""
    def __init__(self):
        self.flags: list[str] = []

    @property
    def is_clean(self) -> bool:
        return len(self.flags) == 0

    def add(self, flag: str) -> None:
        self.flags.append(flag)


def check_output(text: str) -> OutputFlag:
    """
    Scan an assistant response for PHI leakage and medical advice.

    Returns an OutputFlag; callers append the disclaimer when not clean.
    """
    flag = OutputFlag()

    if _SSN_PATTERN.search(text):
        flag.add("ssn_pattern")
    if _MRN_PATTERN.search(text):
        flag.add("mrn_pattern")
    if _FULL_DOB_IN_OUT.search(text):
        flag.add("dob_in_output")
    for key, pattern in _MEDICAL_ADVICE_PATTERNS:
        if pattern.search(text):
            flag.add(key)

    return flag


def sanitize_output(text: str, flag: OutputFlag) -> str:
    """
    Redact raw PHI and append a disclaimer when the output is flagged.

    Booking confirmations and normal scheduling language are left intact.
    """
    if flag.is_clean:
        return text

    # Redact SSN/MRN patterns in-place.
    text = _SSN_PATTERN.sub("[REDACTED-SSN]", text)
    text = _MRN_PATTERN.sub("[REDACTED-MRN]", text)

    # Append disclaimer once.
    if _DISCLAIMER.strip() not in text:
        text += _DISCLAIMER

    return text


def verify_booking_in_response(response_text: str, confirmed_number: Optional[str]) -> bool:
    """
    Cross-check that any confirmation number mentioned in the response
    matches the one actually returned by the book_appointment tool.

    Returns True if consistent (or no confirmation in response), False if mismatch.
    """
    # Look for CCA-XXXXXXXX style confirmation numbers in the response.
    found = re.findall(r"\bCCA-[0-9A-F]{8}\b", response_text)
    if not found:
        return True  # No confirmation mentioned — nothing to cross-check.
    if confirmed_number is None:
        return False  # Response claims a booking but none was made.
    return all(n == confirmed_number for n in found)
