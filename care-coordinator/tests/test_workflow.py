import pytest

from workflow import (
    WorkflowState,
    create_session,
    get_required_fields,
    can_advance,
    advance,
    add_referral,
    get_session_summary,
    transition_to,
)


class TestCreateSession:
    def test_initial_state_is_greet(self):
        session = create_session()
        assert session["state"] == WorkflowState.GREET

    def test_session_has_uuid(self):
        session = create_session()
        assert len(session["session_id"]) == 36  # UUID format

    def test_patient_not_set(self):
        session = create_session()
        assert session["patient_id"] is None
        assert session["patient_confirmed"] is False

    def test_no_referrals(self):
        session = create_session()
        assert session["referrals"] == []


class TestGetRequiredFields:
    def test_greet_needs_nothing(self):
        assert get_required_fields(WorkflowState.GREET) == {}

    def test_verify_patient_needs_id_and_confirmation(self):
        fields = get_required_fields(WorkflowState.VERIFY_PATIENT)
        assert "patient_id" in fields
        assert "patient_confirmed" in fields

    def test_collect_referral_needs_specialty_provider_location(self):
        fields = get_required_fields(WorkflowState.COLLECT_REFERRAL)
        assert "referral.specialty" in fields
        assert "referral.provider_id" in fields
        assert "referral.location_id" in fields


class TestCanAdvance:
    def test_greet_always(self):
        session = create_session()
        assert can_advance(session) is True

    def test_verify_patient_blocked_without_data(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_PATIENT
        assert can_advance(session) is False

    def test_verify_patient_passes_with_data(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_PATIENT
        session["patient_id"] = 1
        session["patient_confirmed"] = True
        assert can_advance(session) is True

    def test_collect_referral_blocked_without_fields(self):
        session = create_session()
        session["state"] = WorkflowState.COLLECT_REFERRAL
        add_referral(session)
        assert can_advance(session) is False

    def test_collect_referral_passes_with_fields(self):
        session = create_session()
        session["state"] = WorkflowState.COLLECT_REFERRAL
        add_referral(session)
        ref = session["referrals"][0]
        ref["specialty"] = "Orthopedics"
        ref["provider_id"] = 2
        ref["location_id"] = 3
        assert can_advance(session) is True

    def test_determine_appt_type_blocked(self):
        session = create_session()
        session["state"] = WorkflowState.DETERMINE_APPT_TYPE
        add_referral(session)
        assert can_advance(session) is False

    def test_determine_appt_type_passes(self):
        session = create_session()
        session["state"] = WorkflowState.DETERMINE_APPT_TYPE
        add_referral(session)
        session["referrals"][0]["appointment_type"] = "NEW"
        assert can_advance(session) is True

    def test_check_availability_blocked(self):
        session = create_session()
        session["state"] = WorkflowState.CHECK_AVAILABILITY
        add_referral(session)
        assert can_advance(session) is False

    def test_check_availability_passes(self):
        session = create_session()
        session["state"] = WorkflowState.CHECK_AVAILABILITY
        add_referral(session)
        session["referrals"][0]["slot_id"] = "slot-123"
        assert can_advance(session) is True

    def test_verify_insurance_blocked(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_INSURANCE
        add_referral(session)
        assert can_advance(session) is False

    def test_verify_insurance_passes(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_INSURANCE
        add_referral(session)
        session["referrals"][0]["insurance_verified"] = True
        assert can_advance(session) is True

    def test_execute_booking_blocked(self):
        session = create_session()
        session["state"] = WorkflowState.EXECUTE_BOOKING
        add_referral(session)
        assert can_advance(session) is False

    def test_execute_booking_passes(self):
        session = create_session()
        session["state"] = WorkflowState.EXECUTE_BOOKING
        add_referral(session)
        session["referrals"][0]["booked"] = True
        assert can_advance(session) is True


class TestAdvance:
    def test_greet_to_verify_patient(self):
        session = create_session()
        advance(session)
        assert session["state"] == WorkflowState.VERIFY_PATIENT

    def test_verify_patient_to_collect_referral(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_PATIENT
        session["patient_id"] = 1
        session["patient_confirmed"] = True
        advance(session)
        assert session["state"] == WorkflowState.COLLECT_REFERRAL

    def test_advance_raises_on_missing_requirements(self):
        session = create_session()
        session["state"] = WorkflowState.VERIFY_PATIENT
        with pytest.raises(ValueError, match="Cannot advance"):
            advance(session)

    def test_full_linear_progression(self):
        session = create_session()
        advance(session)  # → VERIFY_PATIENT
        session["patient_id"] = 1
        session["patient_confirmed"] = True
        advance(session)  # → COLLECT_REFERRAL
        add_referral(session)
        ref = session["referrals"][0]
        ref["specialty"] = "Orthopedics"
        ref["provider_id"] = 2
        ref["location_id"] = 3
        advance(session)  # → DETERMINE_APPT_TYPE
        ref["appointment_type"] = "NEW"
        advance(session)  # → CHECK_AVAILABILITY
        ref["slot_id"] = "slot-xyz"
        advance(session)  # → VERIFY_INSURANCE
        ref["insurance_verified"] = True
        advance(session)  # → CONFIRM_BOOKING
        advance(session)  # → EXECUTE_BOOKING
        ref["booked"] = True
        advance(session)  # → BOOKING_CONFIRMED
        advance(session)  # → FINAL_SUMMARY
        assert session["state"] == WorkflowState.FINAL_SUMMARY


class TestTransitionTo:
    def test_branch_to_suggest_alternatives(self):
        session = create_session()
        session["state"] = WorkflowState.CHECK_AVAILABILITY
        transition_to(session, WorkflowState.SUGGEST_ALTERNATIVES)
        assert session["state"] == WorkflowState.SUGGEST_ALTERNATIVES

    def test_branch_back_to_collect_referral(self):
        session = create_session()
        session["state"] = WorkflowState.BOOKING_CONFIRMED
        transition_to(session, WorkflowState.COLLECT_REFERRAL)
        assert session["state"] == WorkflowState.COLLECT_REFERRAL


class TestAddReferral:
    def test_adds_blank_referral(self):
        session = create_session()
        add_referral(session)
        assert len(session["referrals"]) == 1
        assert session["active_referral_index"] == 0

    def test_second_referral(self):
        session = create_session()
        add_referral(session)
        add_referral(session)
        assert len(session["referrals"]) == 2
        assert session["active_referral_index"] == 1


class TestGetSessionSummary:
    def test_empty_summary(self):
        session = create_session()
        summary = get_session_summary(session)
        assert summary["completed_bookings"] == []

    def test_summary_with_booking(self):
        session = create_session()
        session["patient_id"] = 1
        add_referral(session)
        session["referrals"][0].update({
            "specialty": "Orthopedics",
            "provider_id": 2,
            "location_id": 3,
            "appointment_type": "NEW",
            "slot_id": "slot-abc",
            "booked": True,
            "confirmation_number": "CCA-12345678",
        })
        summary = get_session_summary(session)
        assert len(summary["completed_bookings"]) == 1
        assert summary["completed_bookings"][0]["confirmation_number"] == "CCA-12345678"

    def test_multiple_referrals_partial_booking(self):
        session = create_session()
        session["patient_id"] = 1
        add_referral(session)
        session["referrals"][0]["booked"] = True
        session["referrals"][0]["confirmation_number"] = "CCA-A"
        session["referrals"][0]["specialty"] = "Ortho"
        add_referral(session)
        session["referrals"][1]["booked"] = False
        summary = get_session_summary(session)
        assert len(summary["completed_bookings"]) == 1
