import pytest
from datetime import date, time, datetime, timedelta

from core.policy import (
    determine_appointment_type,
    get_appointment_duration,
    get_arrival_instructions,
    get_last_seen_date,
    validate_slot_within_office_hours,
    validate_booking_request,
)
from core.models import OfficeHours, Slot, Patient, Appointment


# ---------- determine_appointment_type ----------

class TestDetermineAppointmentType:
    def test_never_seen_returns_new(self):
        assert determine_appointment_type(None) == "NEW"

    def test_seen_recently_returns_established(self):
        recent = date.today() - timedelta(days=365)
        assert determine_appointment_type(recent) == "ESTABLISHED"

    def test_seen_over_5_years_ago_returns_new(self):
        old = date.today() - timedelta(days=int(6 * 365.25))
        assert determine_appointment_type(old) == "NEW"

    def test_seen_just_under_5_years_returns_established(self):
        within = date.today() - timedelta(days=int(5 * 365.25))
        assert determine_appointment_type(within) == "ESTABLISHED"

    def test_seen_today_returns_established(self):
        assert determine_appointment_type(date.today()) == "ESTABLISHED"


# ---------- get_appointment_duration ----------

class TestGetAppointmentDuration:
    def test_new_is_30(self):
        assert get_appointment_duration("NEW") == 30

    def test_established_is_15(self):
        assert get_appointment_duration("ESTABLISHED") == 15


# ---------- get_arrival_instructions ----------

class TestGetArrivalInstructions:
    def test_new_30_minutes_early(self):
        assert "30 minutes" in get_arrival_instructions("NEW")

    def test_established_10_minutes_early(self):
        assert "10 minutes" in get_arrival_instructions("ESTABLISHED")


# ---------- validate_slot_within_office_hours ----------

class TestValidateSlotWithinOfficeHours:
    MWF_HOURS = [
        OfficeHours(day_of_week=i, open_time=time(9, 0), close_time=time(17, 0))
        for i in range(5)
    ]

    def test_valid_slot_inside_hours(self):
        start = datetime(2026, 3, 30, 10, 0)  # Monday
        end = datetime(2026, 3, 30, 10, 30)
        assert validate_slot_within_office_hours(start, end, self.MWF_HOURS) is True

    def test_slot_before_open(self):
        start = datetime(2026, 3, 30, 8, 0)
        end = datetime(2026, 3, 30, 8, 30)
        assert validate_slot_within_office_hours(start, end, self.MWF_HOURS) is False

    def test_slot_after_close(self):
        start = datetime(2026, 3, 30, 17, 0)
        end = datetime(2026, 3, 30, 17, 30)
        assert validate_slot_within_office_hours(start, end, self.MWF_HOURS) is False

    def test_slot_on_closed_day(self):
        start = datetime(2026, 3, 28, 10, 0)  # Saturday
        end = datetime(2026, 3, 28, 10, 30)
        assert validate_slot_within_office_hours(start, end, self.MWF_HOURS) is False

    def test_slot_at_exact_boundaries(self):
        start = datetime(2026, 3, 30, 9, 0)
        end = datetime(2026, 3, 30, 17, 0)
        assert validate_slot_within_office_hours(start, end, self.MWF_HOURS) is True


# ---------- get_last_seen_date ----------

class TestGetLastSeenDate:
    APPTS = [
        Appointment(id=1, patient_id=1, provider_id=1,
                    date=date(2018, 3, 5), time=time(9, 15), status="completed"),
        Appointment(id=2, patient_id=1, provider_id=2,
                    date=date(2024, 8, 12), time=time(14, 30), status="completed"),
        Appointment(id=3, patient_id=1, provider_id=1,
                    date=date(2024, 9, 17), time=time(10, 0), status="noshow"),
    ]

    def test_returns_latest_completed(self):
        assert get_last_seen_date(1, 1, self.APPTS) == date(2018, 3, 5)

    def test_different_provider(self):
        assert get_last_seen_date(1, 2, self.APPTS) == date(2024, 8, 12)

    def test_no_history(self):
        assert get_last_seen_date(99, 1, self.APPTS) is None

    def test_only_noshows_not_counted(self):
        noshows = [
            Appointment(id=10, patient_id=5, provider_id=3,
                        date=date(2024, 1, 1), time=time(9, 0), status="noshow"),
        ]
        assert get_last_seen_date(5, 3, noshows) is None


# ---------- validate_booking_request ----------

class TestValidateBookingRequest:
    def _make_db(self):
        patients = {
            1: Patient(id=1, first_name="John", last_name="Doe",
                       dob=date(1975, 1, 1), pcp="Dr. Grey", ehr_id="x"),
        }
        hours = [
            OfficeHours(day_of_week=i, open_time=time(9, 0), close_time=time(17, 0))
            for i in range(5)
        ]
        from core.models import Department
        dept = Department(id=1, name="Test", phone="", address="", hours=hours)
        departments = {1: dept}
        providers = {}

        slot = Slot(
            id="slot-test", provider_id=1, department_id=1,
            start=datetime(2026, 3, 30, 10, 0),
            end=datetime(2026, 3, 30, 10, 30),
            duration_minutes=30, is_available=True,
        )
        slots = {"slot-test": slot}
        appointments: list[Appointment] = []
        return slots, patients, appointments, departments, providers

    def test_valid_request(self):
        slots, patients, appts, depts, provs = self._make_db()
        result = validate_booking_request(
            1, "slot-test", "NEW", slots, patients, appts, depts, provs
        )
        assert result["valid"] is True
        assert result["errors"] == []

    def test_patient_not_found(self):
        slots, patients, appts, depts, provs = self._make_db()
        result = validate_booking_request(
            99, "slot-test", "NEW", slots, patients, appts, depts, provs
        )
        assert result["valid"] is False
        assert any("Patient 99" in e for e in result["errors"])

    def test_slot_not_found(self):
        slots, patients, appts, depts, provs = self._make_db()
        result = validate_booking_request(
            1, "missing", "NEW", slots, patients, appts, depts, provs
        )
        assert result["valid"] is False

    def test_slot_unavailable(self):
        slots, patients, appts, depts, provs = self._make_db()
        slots["slot-test"].is_available = False
        result = validate_booking_request(
            1, "slot-test", "NEW", slots, patients, appts, depts, provs
        )
        assert result["valid"] is False
        assert any("not available" in e for e in result["errors"])

    def test_type_corrected_with_warning(self):
        slots, patients, appts, depts, provs = self._make_db()
        # Add a recent completed appointment → ESTABLISHED
        appts.append(Appointment(
            id=100, patient_id=1, provider_id=1,
            date=date.today() - timedelta(days=30),
            time=time(9, 0), status="completed",
        ))
        result = validate_booking_request(
            1, "slot-test", "NEW", slots, patients, appts, depts, provs
        )
        assert result["corrected_type"] == "ESTABLISHED"
        assert len(result["warnings"]) > 0

    def test_insufficient_duration(self):
        slots, patients, appts, depts, provs = self._make_db()
        slots["slot-test"].duration_minutes = 15
        result = validate_booking_request(
            1, "slot-test", "NEW", slots, patients, appts, depts, provs
        )
        assert result["valid"] is False
        assert any("duration" in e.lower() for e in result["errors"])
