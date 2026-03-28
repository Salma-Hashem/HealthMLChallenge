"""Tests for audit_log.py — Issue #24."""

import hashlib
import json
import os
import tempfile
import uuid

import pytest

import audit_log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    """Redirect the audit log to a temp file for each test."""
    log_file = str(tmp_path / "audit.jsonl")
    monkeypatch.setattr(audit_log, "_LOG_PATH", log_file)
    return log_file


# ---------------------------------------------------------------------------
# Issue #24 acceptance criteria
# ---------------------------------------------------------------------------

class TestLogFormat:
    def test_all_entries_have_required_fields(self, tmp_log):
        trace_id = audit_log.new_trace_id()
        audit_log.log_message_received(trace_id, "sess-1", 42)
        entries = _read_jsonl(tmp_log)
        assert len(entries) == 1
        e = entries[0]
        assert "timestamp" in e
        assert "trace_id" in e
        assert "session_id" in e
        assert "event" in e

    def test_trace_id_is_uuid(self):
        tid = audit_log.new_trace_id()
        # Should not raise
        uuid.UUID(tid)

    def test_log_is_append_only(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_message_received(tid, "s1", 10)
        audit_log.log_response_sent(tid, "s1", 20)
        entries = _read_jsonl(tmp_log)
        assert len(entries) == 2
        assert entries[0]["event"] == "message_received"
        assert entries[1]["event"] == "response_sent"

    def test_each_event_has_trace_id_correlation(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_message_received(tid, "s1", 10)
        audit_log.log_tool_called(tid, "s1", "verify_patient", ["first_name"])
        audit_log.log_response_sent(tid, "s1", 50)
        entries = _read_jsonl(tmp_log)
        assert all(e["trace_id"] == tid for e in entries)


class TestPHIAbsent:
    def test_patient_id_not_in_log_raw(self, tmp_log):
        """Raw integer patient_id must NOT appear — only a hash."""
        raw_id = 42
        expected_hash = hashlib.sha256(str(raw_id).encode()).hexdigest()[:12]
        tid = audit_log.new_trace_id()
        audit_log.log_booking_attempt(tid, "s1", raw_id, "slot-001", "NEW")
        entries = _read_jsonl(tmp_log)
        assert len(entries) == 1
        entry = entries[0]
        # Hash present
        assert entry["patient_id_hash"] == expected_hash
        # Raw integer must not appear under any key named *patient_id* (without hash)
        assert "patient_id" not in entry or entry.get("patient_id") != raw_id

    def test_booking_attempt_has_payload_hash(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_booking_attempt(tid, "s1", 7, "slot-XYZ", "ESTABLISHED")
        entries = _read_jsonl(tmp_log)
        assert "payload_hash" in entries[0]
        assert len(entries[0]["payload_hash"]) == 64  # SHA-256 hex digest

    def test_tool_call_stores_only_arg_keys(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_tool_called(
            tid, "s1", "verify_patient",
            ["first_name", "last_name", "dob"],
        )
        entries = _read_jsonl(tmp_log)
        e = entries[0]
        assert e["arg_keys"] == ["first_name", "last_name", "dob"]
        # No actual values should be stored
        assert "first_name" not in e
        assert "last_name" not in e
        assert "dob" not in e


class TestEventTypes:
    def test_message_received(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_message_received(tid, "s1", 99)
        e = _read_jsonl(tmp_log)[0]
        assert e["event"] == "message_received"
        assert e["message_length"] == 99

    def test_input_blocked(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_input_blocked(tid, "s1", "injection detected", "jailbreak")
        e = _read_jsonl(tmp_log)[0]
        assert e["event"] == "input_blocked"
        assert e["reason"] == "injection detected"
        assert e["pattern_key"] == "jailbreak"

    def test_output_flagged(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_output_flagged(tid, "s1", ["ssn_pattern", "dosage_advice"])
        e = _read_jsonl(tmp_log)[0]
        assert e["event"] == "output_flagged"
        assert "ssn_pattern" in e["flags"]
        assert "dosage_advice" in e["flags"]

    def test_response_sent(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_response_sent(tid, "s1", 200)
        e = _read_jsonl(tmp_log)[0]
        assert e["event"] == "response_sent"
        assert e["response_length"] == 200

    def test_null_session_id_allowed(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_message_received(tid, None, 5)
        e = _read_jsonl(tmp_log)[0]
        assert e["session_id"] is None


class TestPayloadHashIntegrity:
    def test_same_payload_same_hash(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_booking_attempt(tid, "s1", 10, "slot-A", "NEW")
        audit_log.log_booking_attempt(tid, "s1", 10, "slot-A", "NEW")
        entries = _read_jsonl(tmp_log)
        assert entries[0]["payload_hash"] == entries[1]["payload_hash"]

    def test_different_slots_different_hash(self, tmp_log):
        tid = audit_log.new_trace_id()
        audit_log.log_booking_attempt(tid, "s1", 10, "slot-A", "NEW")
        audit_log.log_booking_attempt(tid, "s1", 10, "slot-B", "NEW")
        entries = _read_jsonl(tmp_log)
        assert entries[0]["payload_hash"] != entries[1]["payload_hash"]
