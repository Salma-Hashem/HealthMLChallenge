"""
Tests for data model to_dict() methods and new model classes.
Covers Issue #2 acceptance criteria.
"""

import pytest
from datetime import date, time, datetime

from models import (
    OfficeHours, Department, Provider, ReferredProvider,
    Patient, Appointment, Slot, InsuranceInfo,
    InsurancePlan, SelfPayRate, BookingRequest, BookingConfirmation,
)


# ---------- OfficeHours.to_dict() ----------

class TestOfficeHoursToDict:
    def test_monday_format(self):
        oh = OfficeHours(day_of_week=0, open_time=time(9, 0), close_time=time(17, 0))
        d = oh.to_dict()
        assert d == {"day": "monday", "open": "09:00", "close": "17:00"}

    def test_friday_format(self):
        oh = OfficeHours(day_of_week=4, open_time=time(10, 0), close_time=time(16, 0))
        d = oh.to_dict()
        assert d == {"day": "friday", "open": "10:00", "close": "16:00"}

    def test_tuesday_thursday_format(self):
        oh = OfficeHours(day_of_week=1, open_time=time(10, 0), close_time=time(16, 0))
        d = oh.to_dict()
        assert d["day"] == "tuesday"

    def test_time_zero_padded(self):
        oh = OfficeHours(day_of_week=2, open_time=time(9, 0), close_time=time(17, 0))
        d = oh.to_dict()
        assert d["open"] == "09:00"
        assert d["close"] == "17:00"


# ---------- Department.to_dict() ----------

class TestDepartmentToDict:
    def test_fields_present(self):
        dept = Department(id=1, name="PPTH Orthopedics", phone="(555) 000-0001",
                          address="123 Main St, Greensboro, NC")
        d = dept.to_dict()
        assert d["id"] == 1
        assert d["name"] == "PPTH Orthopedics"
        assert d["phone"] == "(555) 000-0001"
        assert d["address"] == "123 Main St, Greensboro, NC"
        assert d["hours"] == []

    def test_hours_serialized(self):
        oh = OfficeHours(day_of_week=0, open_time=time(9, 0), close_time=time(17, 0))
        dept = Department(id=2, name="Test Dept", phone="", address="", hours=[oh])
        d = dept.to_dict()
        assert len(d["hours"]) == 1
        assert d["hours"][0]["day"] == "monday"


# ---------- Provider.to_dict() ----------

class TestProviderToDict:
    def test_fields_present(self):
        p = Provider(id=1, last_name="Grey", first_name="Meredith",
                     certification="MD", specialty="Primary Care")
        d = p.to_dict()
        assert d["id"] == 1
        assert d["first_name"] == "Meredith"
        assert d["last_name"] == "Grey"
        assert d["certification"] == "MD"
        assert d["specialty"] == "Primary Care"
        assert d["departments"] == []

    def test_departments_nested(self):
        dept = Department(id=1, name="Test", phone="", address="")
        p = Provider(id=2, last_name="House", first_name="Gregory",
                     certification="MD", specialty="Orthopedics", departments=[dept])
        d = p.to_dict()
        assert len(d["departments"]) == 1
        assert d["departments"][0]["name"] == "Test"


# ---------- ReferredProvider.to_dict() ----------

class TestReferredProviderToDict:
    def test_with_provider(self):
        r = ReferredProvider(specialty="Orthopedics", provider_name="House, Gregory MD", provider_id=2)
        d = r.to_dict()
        assert d == {"specialty": "Orthopedics", "provider_name": "House, Gregory MD", "provider_id": 2}

    def test_specialty_only(self):
        r = ReferredProvider(specialty="Primary Care")
        d = r.to_dict()
        assert d["specialty"] == "Primary Care"
        assert d["provider_name"] is None
        assert d["provider_id"] is None


# ---------- Patient.to_dict() ----------

class TestPatientToDict:
    def test_basic_fields(self):
        p = Patient(id=1, first_name="John", last_name="Doe",
                    dob=date(1975, 1, 1), pcp="Dr. Grey",
                    ehr_id="1234abcd", insurance="Aetna")
        d = p.to_dict()
        assert d["id"] == 1
        assert d["first_name"] == "John"
        assert d["last_name"] == "Doe"
        assert d["dob"] == "1975-01-01"
        assert d["pcp"] == "Dr. Grey"
        assert d["ehr_id"] == "1234abcd"
        assert d["insurance"] == "Aetna"
        assert d["referred_providers"] == []

    def test_dob_is_iso_string(self):
        p = Patient(id=2, first_name="Jane", last_name="Smith",
                    dob=date(1990, 5, 15), pcp="Dr. Perry",
                    ehr_id="xyz789")
        d = p.to_dict()
        assert d["dob"] == "1990-05-15"


# ---------- Appointment.to_dict() ----------

class TestAppointmentToDict:
    def test_fields_present(self):
        appt = Appointment(id=1, patient_id=1, provider_id=2,
                           date=date(2024, 8, 12), time=time(14, 30),
                           status="completed", appointment_type="ESTABLISHED")
        d = appt.to_dict()
        assert d["id"] == 1
        assert d["patient_id"] == 1
        assert d["provider_id"] == 2
        assert d["date"] == "2024-08-12"
        assert d["time"] == "14:30"
        assert d["status"] == "completed"
        assert d["appointment_type"] == "ESTABLISHED"

    def test_optional_fields_none(self):
        appt = Appointment(id=2, patient_id=1, provider_id=1,
                           date=date(2018, 3, 5), time=time(9, 15),
                           status="completed")
        d = appt.to_dict()
        assert d["confirmation_number"] is None
        assert d["reason"] is None


# ---------- Slot.to_dict() ----------

class TestSlotToDict:
    def test_fields_present(self):
        s = Slot(id="slot-1-1-2026-03-28-0900", provider_id=1,
                 department_id=2,
                 start=datetime(2026, 3, 28, 9, 0),
                 end=datetime(2026, 3, 28, 9, 30),
                 duration_minutes=30, is_available=True)
        d = s.to_dict()
        assert d["id"] == "slot-1-1-2026-03-28-0900"
        assert d["provider_id"] == 1
        assert d["department_id"] == 2
        assert d["location_id"] == 2         # alias
        assert d["duration_minutes"] == 30
        assert d["is_available"] is True

    def test_unavailable_slot(self):
        s = Slot(id="slot-x", provider_id=1, department_id=1,
                 start=datetime(2026, 3, 28, 9, 0),
                 end=datetime(2026, 3, 28, 9, 15),
                 duration_minutes=15, is_available=False)
        d = s.to_dict()
        assert d["is_available"] is False


# ---------- InsuranceInfo.to_dict() ----------

class TestInsuranceInfoToDict:
    def test_fields(self):
        info = InsuranceInfo(
            accepted_plans=["Aetna", "Cigna"],
            self_pay_rates={"Primary Care": 150.0}
        )
        d = info.to_dict()
        assert d["accepted_plans"] == ["Aetna", "Cigna"]
        assert d["self_pay_rates"]["Primary Care"] == 150.0


# ---------- InsurancePlan ----------

class TestInsurancePlan:
    def test_accepted(self):
        p = InsurancePlan(name="Aetna", accepted=True)
        assert p.to_dict() == {"name": "Aetna", "accepted": True}

    def test_not_accepted(self):
        p = InsurancePlan(name="Kaiser", accepted=False)
        assert p.to_dict() == {"name": "Kaiser", "accepted": False}


# ---------- SelfPayRate ----------

class TestSelfPayRate:
    def test_primary_care(self):
        r = SelfPayRate(specialty="Primary Care", amount=150.0)
        assert r.to_dict() == {"specialty": "Primary Care", "amount": 150.0}

    def test_surgery(self):
        r = SelfPayRate(specialty="Surgery", amount=1000.0)
        assert r.to_dict() == {"specialty": "Surgery", "amount": 1000.0}


# ---------- BookingRequest ----------

class TestBookingRequest:
    def test_all_fields(self):
        req = BookingRequest(patient_id=1, slot_id="slot-1-1-2026-0900",
                             appointment_type="NEW", reason="Follow-up")
        d = req.to_dict()
        assert d["patient_id"] == 1
        assert d["slot_id"] == "slot-1-1-2026-0900"
        assert d["appointment_type"] == "NEW"
        assert d["reason"] == "Follow-up"

    def test_default_reason(self):
        req = BookingRequest(patient_id=1, slot_id="slot-x", appointment_type="ESTABLISHED")
        d = req.to_dict()
        assert d["reason"] == ""


# ---------- BookingConfirmation ----------

class TestBookingConfirmation:
    def test_all_fields(self):
        appt_dt = datetime(2026, 3, 28, 9, 0)
        conf = BookingConfirmation(
            confirmation_number="CCA-12345678",
            patient_name="John Doe",
            provider_name="Dr. Gregory House",
            location="PPTH Orthopedics, 123 Main St, Greensboro, NC",
            appt_datetime=appt_dt,
            type="ESTABLISHED",
            arrival_instructions="Please arrive 10 minutes before your appointment.",
        )
        d = conf.to_dict()
        assert d["confirmation_number"] == "CCA-12345678"
        assert d["patient_name"] == "John Doe"
        assert d["provider_name"] == "Dr. Gregory House"
        assert d["type"] == "ESTABLISHED"
        assert d["datetime"] == appt_dt.isoformat()
        assert "10 minutes" in d["arrival_instructions"]

    def test_new_patient_arrival(self):
        conf = BookingConfirmation(
            confirmation_number="CCA-ABCD1234",
            patient_name="John Doe",
            provider_name="Dr. Meredith Grey",
            location="Sloan Primary Care",
            appt_datetime=datetime(2026, 4, 1, 10, 0),
            type="NEW",
            arrival_instructions="Please arrive 30 minutes before your appointment.",
        )
        d = conf.to_dict()
        assert d["type"] == "NEW"
        assert "30 minutes" in d["arrival_instructions"]
