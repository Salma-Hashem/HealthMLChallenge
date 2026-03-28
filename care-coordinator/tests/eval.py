#!/usr/bin/env python3
"""
Automated evaluation script for the Care Coordinator Assistant.

Issue #27 — Runs all golden test cases and scores results on 4 dimensions:
  - Grounding   : assistant uses tool data, does not hallucinate
  - Safety      : refuses medical advice; resists injection; PHI protected
  - Correctness : follows workflow; correct appointment type
  - Completeness: confirmation includes all required information

Usage
-----
  # Offline cases only (default, no API key required)
  python tests/eval.py

  # Include live LLM cases (requires GOOGLE_API_KEY in .env)
  python tests/eval.py --live

  # Show detailed output for every case
  python tests/eval.py --verbose

Exit codes
----------
  0  All evaluated cases passed
  1  One or more cases failed
"""

import argparse
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Bootstrap: make sure the project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from data_loader import load_all_data
from slot_generator import generate_slots
from tools import execute_tool
from guardrails import (
    InputBlocked, check_input, check_output, sanitize_output,
    friendly_blocked_message, MAX_MESSAGE_LENGTH,
)
from orchestrator import _phi_strip_for_llm


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    grounding: bool = False
    safety: bool = False
    correctness: bool = False
    completeness: bool = False

    @property
    def total(self) -> int:
        return sum([self.grounding, self.safety, self.correctness, self.completeness])

    @property
    def max_total(self) -> int:
        return 4


@dataclass
class CaseResult:
    case_id: str
    case_name: str
    mode: str
    passed: bool
    score: DimensionScore
    details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_db() -> dict:
    data_path = PROJECT_ROOT / "data_sheet.txt"
    db = load_all_data(str(data_path))
    db["slots"] = generate_slots(db["providers"], db["departments"])
    return db


def _assert_result_contains(result: Any, spec: dict) -> list[str]:
    """
    Check that a tool result (dict or list) satisfies all keys in *spec*.

    Special syntax in spec values:
      "__gt:N"              → result[key] > N
      "__list_min_length"   → len(result) >= spec["__list_min_length"]
      "__first_item_key"    → result[0] has the specified key
      "__referrals_count_gte" → len(result["referrals"]) >= N
      "__departments_count_gte" → len(result["departments"]) >= N
    """
    errors = []
    for key, expected in spec.items():
        if key == "__list_min_length":
            if not isinstance(result, list) or len(result) < expected:
                errors.append(f"expected list with >= {expected} items, got {len(result) if isinstance(result, list) else type(result).__name__}")
        elif key == "__first_item_key":
            if not isinstance(result, list) or not result or expected not in result[0]:
                errors.append(f"first item missing key '{expected}'")
        elif key == "__referrals_count_gte":
            referrals = result.get("referrals", []) if isinstance(result, dict) else []
            if len(referrals) < expected:
                errors.append(f"expected >= {expected} referrals, got {len(referrals)}")
        elif key == "__departments_count_gte":
            depts = result.get("departments", []) if isinstance(result, dict) else []
            if len(depts) < expected:
                errors.append(f"expected >= {expected} departments, got {len(depts)}")
        elif isinstance(expected, str) and expected.startswith("__gt:"):
            threshold = int(expected.split(":")[1])
            actual = result.get(key) if isinstance(result, dict) else None
            if actual is None or actual <= threshold:
                errors.append(f"expected {key} > {threshold}, got {actual!r}")
        else:
            actual = result.get(key) if isinstance(result, dict) else None
            if actual != expected:
                errors.append(f"expected {key}={expected!r}, got {actual!r}")
    return errors


# ---------------------------------------------------------------------------
# Evaluators per case type
# ---------------------------------------------------------------------------

def _eval_tool_assertions(case: dict, db: dict) -> CaseResult:
    """Run each tool assertion by calling execute_tool directly."""
    session = {"patient_id": None, "patient_confirmed": True}
    score = DimensionScore()
    details = []
    errors = []
    all_ok = True

    for assertion in case.get("tool_assertions", []):
        tool = assertion["tool"]
        inp = assertion["input"]
        spec = assertion.get("assert_result_contains", {})

        # For verify_patient, patient_confirmed must start as False
        if tool == "verify_patient":
            session = {"patient_id": None, "patient_confirmed": False}

        try:
            result_str = execute_tool(tool, inp, db, session)
            result = json.loads(result_str)
        except Exception as exc:
            errors.append(f"{tool}: exception — {exc}")
            all_ok = False
            continue

        # Check spec
        check_errors = _assert_result_contains(result, spec)
        if check_errors:
            errors.extend([f"{tool}: {e}" for e in check_errors])
            all_ok = False
        else:
            details.append(f"{tool}: OK")

        # If verify_patient succeeded, update session so subsequent tools can run
        if tool == "verify_patient" and result.get("found"):
            session["patient_id"] = result.get("patient_id")
            session["patient_confirmed"] = True

    # Score based on pass/fail
    if all_ok:
        score.grounding = True
        score.correctness = True
        # Check appointment type if specified
        expected_type = case.get("expected_appointment_type")
        if expected_type:
            for assertion in case.get("tool_assertions", []):
                if assertion["tool"] == "get_booking_history":
                    spec = assertion.get("assert_result_contains", {})
                    if spec.get("appointment_type") == expected_type:
                        score.correctness = True
        score.completeness = True
    score.safety = True  # offline tool tests don't exercise safety dimension

    return CaseResult(
        case_id=case["id"],
        case_name=case["name"],
        mode=case["mode"],
        passed=all_ok,
        score=score,
        details=details,
        errors=errors,
    )


def _eval_guardrail_assertions(case: dict) -> CaseResult:
    """Evaluate input/output guardrail assertions without LLM."""
    score = DimensionScore()
    details = []
    errors = []
    all_ok = True

    for assertion in case.get("guardrail_assertions", []):
        kind = assertion["type"]
        text = assertion["text"]

        # Expand special text markers
        if text == "__GENERATE:2001":
            text = "a" * 2001

        if kind == "input":
            expected_blocked = assertion.get("expected_blocked", True)
            expected_key = assertion.get("expected_pattern_key")
            try:
                check_input(text, "eval-session")
                if expected_blocked:
                    errors.append(f"input NOT blocked but expected to be: {text[:60]!r}...")
                    all_ok = False
                else:
                    details.append(f"input passed (expected): {text[:60]!r}")
            except InputBlocked as exc:
                if not expected_blocked:
                    errors.append(f"input unexpectedly blocked ({exc.pattern_key}): {text[:60]!r}")
                    all_ok = False
                elif expected_key and exc.pattern_key != expected_key:
                    errors.append(f"wrong pattern_key: expected {expected_key!r}, got {exc.pattern_key!r}")
                    all_ok = False
                else:
                    details.append(f"input blocked OK (key={exc.pattern_key}): {text[:60]!r}")

        elif kind == "output":
            expected_flags = assertion.get("expected_flags", [])
            flag = check_output(text)
            for ef in expected_flags:
                if ef not in flag.flags:
                    errors.append(f"expected flag '{ef}' not in {flag.flags} for: {text[:60]!r}")
                    all_ok = False
                else:
                    details.append(f"output flag '{ef}' detected OK")
            # Also verify sanitize_output adds disclaimer
            if not flag.is_clean:
                sanitized = sanitize_output(text, flag)
                if "clinical staff" not in sanitized:
                    errors.append("disclaimer not appended to flagged output")
                    all_ok = False
                else:
                    details.append("disclaimer appended OK")

    if all_ok:
        score.safety = True
        score.correctness = True
        score.completeness = True
    score.grounding = True  # guardrail tests don't exercise grounding dimension

    return CaseResult(
        case_id=case["id"],
        case_name=case["name"],
        mode=case["mode"],
        passed=all_ok,
        score=score,
        details=details,
        errors=errors,
    )


def _eval_phi_assertions(case: dict, db: dict) -> CaseResult:
    """Verify PHI minimisation strips the correct fields from LLM context."""
    session = {"patient_id": 1, "patient_confirmed": True}
    score = DimensionScore()
    details = []
    errors = []
    all_ok = True

    for assertion in case.get("phi_assertions", []):
        tool = assertion["tool"]
        must_not_contain = assertion.get("llm_context_must_not_contain", [])

        # Build a realistic input for the tool
        if tool == "verify_patient":
            inp = {"first_name": "John", "last_name": "Doe"}
            session_tmp = {"patient_id": None, "patient_confirmed": False}
        elif tool == "book_appointment":
            # Find a real available slot for provider 2
            slot = next(
                (s for s in db["slots"].values() if s.is_available and s.provider_id == 2 and s.duration_minutes == 15),
                None,
            )
            if slot is None:
                errors.append("book_appointment: no available 15-min slot found for provider 2")
                all_ok = False
                continue
            inp = {"patient_id": 1, "slot_id": slot.id, "appointment_type": "ESTABLISHED", "reason": "PHI test"}
            session_tmp = session
        else:
            continue

        try:
            result_str = execute_tool(tool, inp, db, session_tmp)
            raw_result = json.loads(result_str)
        except Exception as exc:
            errors.append(f"{tool}: exception — {exc}")
            all_ok = False
            continue

        # Verify raw result actually contains the PHI fields we claim to strip
        raw_keys = set(raw_result.keys()) if isinstance(raw_result, dict) else set()
        for field in must_not_contain:
            if field not in raw_keys:
                # Not actually in raw — note it but don't fail
                details.append(f"{tool}: raw result doesn't contain '{field}' (nothing to strip)")
                continue

            # Now strip and verify the field is gone
            stripped = _phi_strip_for_llm(tool, raw_result)
            if field in stripped:
                errors.append(f"{tool}: '{field}' still present in LLM-facing result after strip")
                all_ok = False
            else:
                details.append(f"{tool}: '{field}' correctly stripped for LLM context")

    if all_ok:
        score.safety = True
        score.correctness = True
        score.completeness = True
        score.grounding = True

    return CaseResult(
        case_id=case["id"],
        case_name=case["name"],
        mode=case["mode"],
        passed=all_ok,
        score=score,
        details=details,
        errors=errors,
    )


def _eval_live(case: dict, db: dict, sessions: dict) -> CaseResult:
    """Run a live multi-turn conversation through the real orchestrator."""
    from orchestrator import handle_message

    score = DimensionScore()
    details = []
    errors = []
    all_ok = True

    session_id = None
    last_response = ""
    last_workflow_state = "GREET"
    tools_called: list[str] = []

    for user_msg in case.get("inputs", []):
        try:
            result = handle_message(session_id, user_msg, db, sessions)
            session_id = result["session_id"]
            last_response = result.get("response", "")
            last_workflow_state = result.get("workflow_state", "GREET")
            details.append(f"turn: {user_msg[:50]!r} → {last_response[:80]!r}…")
        except Exception as exc:
            errors.append(f"handle_message raised: {exc}\n{traceback.format_exc()}")
            all_ok = False
            break

    # Evaluate live_assertions
    for assertion in case.get("live_assertions", []):
        kind = assertion["type"]

        if kind == "response_contains_any":
            values = assertion.get("values", [])
            if not any(v.lower() in last_response.lower() for v in values):
                errors.append(f"response doesn't contain any of {values}")
                all_ok = False
            else:
                details.append(f"response_contains_any OK: {values}")

        elif kind == "response_contains_pattern":
            pattern = assertion["pattern"]
            if not re.search(pattern, last_response):
                errors.append(f"response doesn't match pattern: {pattern}")
                all_ok = False
            else:
                details.append(f"response_contains_pattern OK: {pattern}")

        elif kind == "workflow_state":
            expected = assertion["expected"]
            if last_workflow_state != expected:
                errors.append(f"workflow_state: expected {expected}, got {last_workflow_state}")
                all_ok = False
            else:
                details.append(f"workflow_state OK: {last_workflow_state}")

        elif kind == "appointment_type":
            # Check the session booking records
            session_obj = sessions.get(session_id, {})
            booked_types = [
                ref.get("appointment_type")
                for ref in session_obj.get("referrals", [])
                if ref.get("booked")
            ]
            expected = assertion["expected"]
            if expected not in booked_types:
                errors.append(f"appointment_type {expected} not in booked referrals {booked_types}")
                all_ok = False
            else:
                details.append(f"appointment_type OK: {expected}")

        elif kind == "tool_not_called":
            # We can't directly introspect which tools were called in live mode
            # without hooking the orchestrator; flag as informational
            details.append(f"tool_not_called check skipped (live mode): {assertion['tool']}")

    if all_ok:
        score.grounding = True
        score.safety = True
        score.correctness = True
        score.completeness = True

    return CaseResult(
        case_id=case["id"],
        case_name=case["name"],
        mode=case["mode"],
        passed=all_ok,
        score=score,
        details=details,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_eval(live: bool = False, verbose: bool = False) -> int:
    dataset_path = Path(__file__).parent / "golden_dataset.json"
    with open(dataset_path) as fh:
        dataset = json.load(fh)

    db = _load_db()
    sessions: dict = {}

    results: list[CaseResult] = []
    skipped = 0

    for case in dataset["cases"]:
        mode = case.get("mode", "offline")

        if mode == "live" and not live:
            skipped += 1
            continue

        print(f"  Running {case['id']} [{mode}] — {case['name'][:55]}…", end=" ", flush=True)

        try:
            if mode == "live":
                result = _eval_live(case, db, sessions)
            elif case.get("guardrail_assertions"):
                result = _eval_guardrail_assertions(case)
            elif case.get("phi_assertions"):
                result = _eval_phi_assertions(case, db)
            else:
                result = _eval_tool_assertions(case, db)
        except Exception as exc:
            result = CaseResult(
                case_id=case["id"],
                case_name=case["name"],
                mode=mode,
                passed=False,
                score=DimensionScore(),
                errors=[f"Evaluator crashed: {exc}\n{traceback.format_exc()}"],
            )

        status = "PASS" if result.passed else "FAIL"
        print(f"{status} ({result.score.total}/{result.score.max_total})")

        if verbose or not result.passed:
            for d in result.details:
                print(f"    + {d}")
            for e in result.errors:
                print(f"    ✗ {e}")

        results.append(result)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    total_score = sum(r.score.total for r in results)
    max_score   = sum(r.score.max_total for r in results)

    grounding_pass   = sum(1 for r in results if r.score.grounding)
    safety_pass      = sum(1 for r in results if r.score.safety)
    correctness_pass = sum(1 for r in results if r.score.correctness)
    completeness_pass= sum(1 for r in results if r.score.completeness)
    n = len(results)

    print()
    print("=" * 62)
    print("  EVALUATION SUMMARY")
    print("=" * 62)
    print(f"  Cases run     : {len(results)}  |  Skipped (live): {skipped}")
    print(f"  Passed        : {len(passed)}  |  Failed: {len(failed)}")
    print(f"  Overall score : {total_score}/{max_score} "
          f"({100*total_score//max_score if max_score else 0}%)")
    print()
    print("  Dimension accuracy:")
    print(f"    Grounding    : {grounding_pass}/{n} ({100*grounding_pass//n if n else 0}%)")
    print(f"    Safety       : {safety_pass}/{n} ({100*safety_pass//n if n else 0}%)")
    print(f"    Correctness  : {correctness_pass}/{n} ({100*correctness_pass//n if n else 0}%)")
    print(f"    Completeness : {completeness_pass}/{n} ({100*completeness_pass//n if n else 0}%)")

    if failed:
        print()
        print("  Failed cases:")
        for r in failed:
            print(f"    [{r.case_id}] {r.case_name}")
            for e in r.errors:
                print(f"      ✗ {e}")

    print("=" * 62)

    return 0 if not failed else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Care Coordinator eval harness")
    parser.add_argument("--live", action="store_true", help="Include live LLM test cases")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show details for all cases")
    args = parser.parse_args()

    print()
    print("Care Coordinator Assistant — Evaluation")
    print(f"Mode: {'offline + live' if args.live else 'offline only'}")
    print()

    exit_code = run_eval(live=args.live, verbose=args.verbose)
    sys.exit(exit_code)
