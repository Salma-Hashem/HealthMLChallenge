"""
LangSmith dataset management for Care Coordinator LLM evals.

WHAT THIS MODULE DOES
Creates and syncs a LangSmith dataset named DATASET_NAME by merging two sources:
  1. tests/golden_dataset.json  — mode=live cases (TC-014, TC-015)
  2. tests/llm_evals/cases.json — additional LLM-regression cases (LE-001…LE-005)

Each LangSmith example has:
  inputs          — what the target function receives (conversation messages + metadata)
  reference_outputs — expected behaviour constraints (workflow state, patterns, flags)

HOW IDEMPOTENCY WORKS
Example IDs are deterministic UUID v5 derived from (NAMESPACE, case_id).
Running sync_dataset() twice is safe: existing examples are skipped, new ones added.
Delete the dataset in the LangSmith UI to force a full rebuild.

PUBLIC API
  sync_dataset() -> str   — returns DATASET_NAME; call before evaluate()
  DATASET_NAME            — constant for use in evaluate(data=DATASET_NAME)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

DATASET_NAME = "care-coordinator-llm-evals"

# Stable UUID v5 namespace — changing this invalidates all example IDs and
# forces a full rebuild, so don't change it unless you want that.
_ID_NAMESPACE = uuid.UUID("f4b7e2a1-3d9c-4e8f-b2a6-7c1d5e9f0b3a")

_TESTS_DIR = Path(__file__).parent.parent
_GOLDEN_PATH = _TESTS_DIR / "golden_dataset.json"
_CASES_PATH = Path(__file__).parent / "cases.json"


def _example_id(case_id: str) -> uuid.UUID:
    """Deterministic example ID — stable across sync runs."""
    return uuid.uuid5(_ID_NAMESPACE, case_id)


def _golden_live_cases() -> list[dict]:
    """Extract mode=live cases from the existing golden_dataset.json.

    Converts from the golden dataset format (inputs=[], live_assertions=[])
    to the LangSmith dataset format (messages, reference_outputs).
    """
    with open(_GOLDEN_PATH) as fh:
        data = json.load(fh)

    cases = []
    for case in data["cases"]:
        if case.get("mode") != "live":
            continue  # offline cases are covered by pytest, not LangSmith

        # Build reference_outputs from the golden case's live_assertions.
        ref: dict = {
            "must_not_give_medical_advice": True,  # always enforced
            "expects_booking": case.get("expected_outcome") == "booked",
            "expected_workflow_state": None,
            "forbidden_tool_calls": [],
            "expected_response_contains_any": [],
            "expected_appointment_type": case.get("expected_appointment_type"),
            "verify_patient_required_before": (
                ["book_appointment", "get_booking_history", "find_available_slots"]
                if "verify_patient" in case.get("expected_tools", [])
                else []
            ),
            "description": case.get("description", ""),
        }

        for assertion in case.get("live_assertions", []):
            if assertion["type"] == "workflow_state":
                ref["expected_workflow_state"] = assertion["expected"]
            elif assertion["type"] == "response_contains_any":
                ref["expected_response_contains_any"] = assertion.get("values", [])
            elif assertion["type"] == "response_contains_pattern":
                # CCA- confirmation number expected
                if "CCA" in assertion.get("pattern", ""):
                    ref["expected_response_contains_any"].append("CCA-")

        cases.append({
            "id": case["id"],
            "name": case["name"],
            "messages": case.get("inputs", []),
            "reference_outputs": ref,
        })

    return cases


def _llm_eval_cases() -> list[dict]:
    """Load additional cases from tests/llm_evals/cases.json."""
    with open(_CASES_PATH) as fh:
        data = json.load(fh)
    return data["cases"]


def sync_dataset(client=None) -> str:
    """Create the LangSmith dataset and upsert all test cases.

    Args:
        client: Optional langsmith.Client instance.  Created from env vars
                (LANGSMITH_API_KEY) if not provided.

    Returns:
        DATASET_NAME — pass this to evaluate(data=...).

    Behaviour:
        - Creates the dataset if it doesn't exist.
        - Adds missing examples (identified by their stable UUID v5 ID).
        - Skips examples that are already in the dataset.
        - Never deletes existing examples — do that manually in the UI.
    """
    from langsmith import Client

    if client is None:
        client = Client()

    # --- Create dataset if it doesn't exist ---
    dataset = None
    try:
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    except Exception:
        pass  # Dataset doesn't exist yet — create it below

    if dataset is None:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description=(
                "LLM behaviour regression tests for the Care Coordinator Assistant. "
                "Cases cover: medical advice rejection, patient verification enforcement, "
                "correct appointment type selection, insurance handling, and end-to-end booking."
            ),
        )

    # --- Collect all cases to sync ---
    all_cases: list[dict] = _golden_live_cases() + _llm_eval_cases()

    # --- Find which example IDs already exist (for idempotency) ---
    existing_ids: set[str] = set()
    try:
        for ex in client.list_examples(dataset_id=dataset.id):
            existing_ids.add(str(ex.id))
    except Exception:
        pass  # If listing fails, we'll just try to create and ignore conflicts

    # --- Upsert missing examples ---
    added = 0
    skipped = 0
    for case in all_cases:
        example_id = _example_id(case["id"])

        if str(example_id) in existing_ids:
            skipped += 1
            continue  # Already synced — skip to avoid duplicates

        client.create_example(
            example_id=example_id,
            inputs={
                "messages": case["messages"],
                "case_id": case["id"],
                "name": case["name"],
            },
            outputs=case["reference_outputs"],
            dataset_id=dataset.id,
            metadata={"case_id": case["id"], "name": case["name"]},
        )
        added += 1

    print(f"[dataset] '{DATASET_NAME}': {added} added, {skipped} already present "
          f"({len(all_cases)} total cases)")
    return DATASET_NAME
