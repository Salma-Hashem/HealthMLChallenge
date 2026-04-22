import pytest

from main import app as flask_app, db
from agent.orchestrator import _build_response


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ---------- Healthcheck ----------

class TestHealthcheck:
    def test_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


# ---------- Legacy patient endpoint ----------

class TestLegacyPatient:
    def test_returns_john_doe(self, client):
        resp = client.get("/patient/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "John Doe"
        assert data["dob"] == "01/01/1975"
        assert data["pcp"] == "Dr. Meredith Grey"
        assert data["ehrId"] == "1234abcd"
        assert len(data["appointments"]) >= 4

    def test_not_found(self, client):
        resp = client.get("/patient/999")
        assert resp.status_code == 404


# ---------- New patient API ----------

class TestPatientAPI:
    def test_get_patient(self, client):
        resp = client.get("/api/patient/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"
        assert data["dob"] == "1975-01-01"

    def test_search_by_name(self, client):
        resp = client.post("/api/patient/search", json={
            "first_name": "John", "last_name": "Doe",
        })
        assert resp.status_code == 200
        results = resp.get_json()
        assert len(results) >= 1
        assert results[0]["first_name"] == "John"

    def test_search_no_match(self, client):
        resp = client.post("/api/patient/search", json={
            "first_name": "Nobody",
        })
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------- Providers API ----------

class TestProvidersAPI:
    def test_list_all(self, client):
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 5

    def test_filter_by_specialty(self, client):
        resp = client.get("/api/providers?specialty=Orthopedics")
        data = resp.get_json()
        assert len(data) == 2
        assert all(p["specialty"] == "Orthopedics" for p in data)

    def test_filter_by_location(self, client):
        resp = client.get("/api/providers?location=Charlotte")
        data = resp.get_json()
        assert len(data) >= 1

    def test_get_single_provider(self, client):
        resp = client.get("/api/providers/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["first_name"] == "Meredith"
        assert data["last_name"] == "Grey"
        assert len(data["departments"]) >= 1
        assert "hours" in data["departments"][0]

    def test_provider_not_found(self, client):
        resp = client.get("/api/providers/999")
        assert resp.status_code == 404

    def test_hours_format(self, client):
        resp = client.get("/api/providers/1")
        data = resp.get_json()
        hours = data["departments"][0]["hours"]
        assert len(hours) > 0
        h = hours[0]
        assert "day" in h
        assert h["day"] == h["day"].lower()   # e.g. "monday" not "Monday"
        assert "open" in h
        assert "close" in h
        # open/close must be HH:MM 24-hour format
        assert len(h["open"]) == 5 and h["open"][2] == ":"
        assert len(h["close"]) == 5 and h["close"][2] == ":"


# ---------- History API ----------

class TestHistoryAPI:
    def test_seen_provider(self, client):
        resp = client.get("/api/history/1/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_seen_date"] == "2018-03-05"
        assert data["appointment_type"] == "NEW"
        assert data["duration_minutes"] == 30

    def test_recently_seen_provider(self, client):
        resp = client.get("/api/history/1/2")
        data = resp.get_json()
        assert data["last_seen_date"] == "2024-08-12"
        assert data["appointment_type"] == "ESTABLISHED"
        assert data["duration_minutes"] == 15

    def test_never_seen(self, client):
        resp = client.get("/api/history/1/99")
        data = resp.get_json()
        assert data["last_seen_date"] is None
        assert data["appointment_type"] == "NEW"


# ---------- Slots API ----------

class TestSlotsAPI:
    def test_search_all_for_provider(self, client):
        resp = client.post("/api/slots/search", json={"provider_id": 1})
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) > 0

    def test_filter_by_duration(self, client):
        resp = client.post("/api/slots/search", json={
            "provider_id": 1, "duration": 30,
        })
        data = resp.get_json()
        assert all(s["duration_minutes"] == 30 for s in data)

    def test_filter_by_location(self, client):
        resp = client.post("/api/slots/search", json={
            "provider_id": 2, "location_id": 2,
        })
        data = resp.get_json()
        assert all(s["department_id"] == 2 for s in data)

    def test_results_are_sorted(self, client):
        resp = client.post("/api/slots/search", json={"provider_id": 1})
        data = resp.get_json()
        starts = [s["start"] for s in data]
        assert starts == sorted(starts)


# ---------- Insurance API ----------

class TestInsuranceAPI:
    def test_accepted_plan(self, client):
        resp = client.get("/api/insurance/check/Aetna")
        data = resp.get_json()
        assert data["accepted"] is True

    def test_case_insensitive(self, client):
        resp = client.get("/api/insurance/check/aetna")
        data = resp.get_json()
        assert data["accepted"] is True

    def test_rejected_plan(self, client):
        resp = client.get("/api/insurance/check/UnknownPlan")
        data = resp.get_json()
        assert data["accepted"] is False
        assert data["self_pay_available"] is True

    def test_selfpay_primary_care(self, client):
        resp = client.get("/api/insurance/selfpay/Primary Care")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["rate"] == 150.0

    def test_selfpay_orthopedics(self, client):
        resp = client.get("/api/insurance/selfpay/Orthopedics")
        data = resp.get_json()
        assert data["rate"] == 300.0

    def test_selfpay_surgery(self, client):
        resp = client.get("/api/insurance/selfpay/Surgery")
        data = resp.get_json()
        assert data["rate"] == 1000.0

    def test_selfpay_unknown(self, client):
        resp = client.get("/api/insurance/selfpay/Dermatology")
        assert resp.status_code == 404

    def test_insurance_check_includes_self_pay_rates(self, client):
        resp = client.get("/api/insurance/check/UnknownPlan")
        data = resp.get_json()
        assert "self_pay_rates" in data
        assert data["self_pay_rates"]["Primary Care"] == 150.0
        assert data["self_pay_rates"]["Orthopedics"] == 300.0
        assert data["self_pay_rates"]["Surgery"] == 1000.0

    def test_accepted_plan_also_has_self_pay_rates(self, client):
        resp = client.get("/api/insurance/check/Aetna")
        data = resp.get_json()
        assert "self_pay_rates" in data


# ---------- Booking API ----------

class TestBookingAPI:
    def test_successful_booking(self, client):
        resp = client.post("/api/slots/search", json={
            "provider_id": 1, "duration": 30,
        })
        slots = resp.get_json()
        available = [s for s in slots if s["is_available"]]
        assert len(available) > 0

        slot_id = available[0]["id"]
        resp = client.post("/api/appointments/book", json={
            "patient_id": 1,
            "slot_id": slot_id,
            "type": "NEW",
            "reason": "Follow-up after discharge",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert "confirmation_number" in data
        assert data["confirmation_number"].startswith("CCA-")
        assert data["appointment"]["type"] == "NEW"
        assert "arrival_instructions" in data

    def test_booking_invalid_patient(self, client):
        resp = client.post("/api/slots/search", json={
            "provider_id": 1, "duration": 30,
        })
        slot_id = [s for s in resp.get_json() if s["is_available"]][0]["id"]
        resp = client.post("/api/appointments/book", json={
            "patient_id": 999,
            "slot_id": slot_id,
            "type": "NEW",
        })
        assert resp.status_code == 400

    def test_booking_invalid_slot(self, client):
        resp = client.post("/api/appointments/book", json={
            "patient_id": 1,
            "slot_id": "nonexistent",
            "type": "NEW",
        })
        assert resp.status_code == 400


# ---------- Workflow state format (BookingChecklist) ----------

class TestWorkflowStateFormat:
    """Ensure workflow_state is always returned as UPPERCASE so the React
    BookingChecklist can match it against its WORKFLOW_STEPS constants."""

    def test_default_state_is_uppercase(self):
        result = _build_response("sid", {}, "hello")
        assert result["workflow_state"] == result["workflow_state"].upper()

    def test_lowercase_state_is_uppercased(self):
        result = _build_response("sid", {"workflow_state": "verify_patient"}, "hello")
        assert result["workflow_state"] == "VERIFY_PATIENT"

    def test_all_known_states_are_uppercased(self):
        from core.workflow import WorkflowState
        for state in WorkflowState:
            result = _build_response("sid", {"workflow_state": state.value}, "hi")
            assert result["workflow_state"] == result["workflow_state"].upper(), (
                f"workflow_state '{state.value}' was not uppercased in API response"
            )
