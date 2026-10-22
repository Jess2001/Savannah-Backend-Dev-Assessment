from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from appointments.models import Appointment
from doctors.models import DoctorWorkingHour, Weekday

User = get_user_model()
pytestmark = pytest.mark.django_db

NAIROBI = ZoneInfo("Africa/Nairobi")


def target_monday():
    """A Monday 7-13 days from today: inside the booking window, whenever tests run."""
    today = timezone.now().astimezone(NAIROBI).date()
    return today + timedelta(days=(7 - today.weekday()) % 7 + 7)


DAY = target_monday()


def at(hour, minute=0):
    local = datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=NAIROBI)
    return local.astimezone(dt_timezone.utc)


def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture
def hours(doctor):
    return DoctorWorkingHour.objects.create(
        doctor=doctor,
        weekday=Weekday.MONDAY,
        start_time=time(8, 0),
        end_time=time(17, 0),
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff_one", password="TestPass123!", role=User.Role.STAFF
    )


def client_as(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def book(user, doctor, start):
    return client_as(user).post(
        "/appointments",
        {"doctor_id": doctor.pk, "start_time": iso(start)},
        format="json",
    )


# ---------- authentication and booking ----------


def test_unauthenticated_request_is_rejected():
    response = APIClient().post("/appointments", {}, format="json")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_patient_can_book(doctor, hours, patient):
    response = book(patient.user, doctor, at(9))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["start_time"] == iso(at(9))
    assert body["local_start_time"].endswith("+03:00")


def test_staff_cannot_book(doctor, hours, staff_user):
    assert book(staff_user, doctor, at(9)).status_code == 403


def test_datetime_without_timezone_is_rejected(doctor, hours, patient):
    response = client_as(patient.user).post(
        "/appointments",
        {"doctor_id": doctor.pk, "start_time": "2030-01-07T09:00:00"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_off_grid_time_returns_400(doctor, hours, patient):
    response = book(patient.user, doctor, at(9, 15))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "booking_rule_violation"


def test_taken_slot_returns_409(doctor, hours, patient, other_patient):
    book(patient.user, doctor, at(9))
    response = book(other_patient.user, doctor, at(9))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_unavailable"


# ---------- availability ----------


def test_availability_excludes_booked_slots(doctor, hours, patient):
    book(patient.user, doctor, at(9))
    response = client_as(patient.user).get(
        f"/doctors/{doctor.pk}/availability", {"date": DAY.isoformat()}
    )
    assert response.status_code == 200
    starts = [slot["start_time"] for slot in response.json()["slots"]]
    assert len(starts) == 17
    assert iso(at(8)) in starts
    assert iso(at(9)) not in starts


def test_availability_requires_a_valid_date(doctor, hours, patient):
    response = client_as(patient.user).get(f"/doctors/{doctor.pk}/availability")
    assert response.status_code == 400


def test_availability_for_unknown_doctor_is_404(patient):
    response = client_as(patient.user).get(
        "/doctors/99999/availability", {"date": DAY.isoformat()}
    )
    assert response.status_code == 404


def test_availability_for_inactive_doctor_is_404(doctor, hours, patient):
    doctor.is_active = False
    doctor.save()
    response = client_as(patient.user).get(
        f"/doctors/{doctor.pk}/availability", {"date": DAY.isoformat()}
    )
    assert response.status_code == 404


# ---------- cancel ----------


def test_patient_can_cancel_own_appointment(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(patient.user).patch(
        f"/appointments/{appointment_id}/cancel",
        {"reason": "Feeling better"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancellation_reason"] == "Feeling better"


def test_cancel_requires_a_reason(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(patient.user).patch(
        f"/appointments/{appointment_id}/cancel", {"reason": "   "}, format="json"
    )
    assert response.status_code == 400


def test_cancelling_twice_returns_409(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    client = client_as(patient.user)
    url = f"/appointments/{appointment_id}/cancel"
    client.patch(url, {"reason": "First"}, format="json")
    response = client.patch(url, {"reason": "Second"}, format="json")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"


def test_other_patients_appointment_looks_like_404(
    doctor, hours, patient, other_patient
):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(other_patient.user).patch(
        f"/appointments/{appointment_id}/cancel", {"reason": "Mine now"}, format="json"
    )
    assert response.status_code == 404


def test_staff_can_cancel_any_appointment(doctor, hours, patient, staff_user):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(staff_user).patch(
        f"/appointments/{appointment_id}/cancel",
        {"reason": "Doctor unavailable"},
        format="json",
    )
    assert response.status_code == 200


def test_doctor_role_has_no_appointment_access(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(doctor.user).patch(
        f"/appointments/{appointment_id}/cancel", {"reason": "x"}, format="json"
    )
    assert response.status_code == 403


# ---------- reschedule ----------


def test_patient_can_reschedule(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    response = client_as(patient.user).patch(
        f"/appointments/{appointment_id}/reschedule",
        {"start_time": iso(at(10))},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["start_time"] == iso(at(10))


def test_cancelled_appointment_cannot_be_rescheduled(doctor, hours, patient):
    appointment_id = book(patient.user, doctor, at(9)).json()["id"]
    client = client_as(patient.user)
    client.patch(
        f"/appointments/{appointment_id}/cancel", {"reason": "Clash"}, format="json"
    )
    response = client.patch(
        f"/appointments/{appointment_id}/reschedule",
        {"start_time": iso(at(10))},
        format="json",
    )
    assert response.status_code == 409


# ---------- patient's upcoming appointments ----------


def test_upcoming_list_is_sorted_and_excludes_cancelled_and_past(
    doctor, hours, patient
):
    ids = {
        hour: book(patient.user, doctor, at(hour)).json()["id"] for hour in (11, 9, 10)
    }
    client_as(patient.user).patch(
        f"/appointments/{ids[10]}/cancel", {"reason": "Clash"}, format="json"
    )
    Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        start_time=timezone.now() - timedelta(days=1),
    )

    response = client_as(patient.user).get(f"/patients/{patient.pk}/appointments")
    assert response.status_code == 200
    assert [item["start_time"] for item in response.json()] == [
        iso(at(9)),
        iso(at(11)),
    ]


def test_patient_cannot_view_another_patients_list(patient, other_patient):
    response = client_as(other_patient.user).get(f"/patients/{patient.pk}/appointments")
    assert response.status_code == 404


def test_staff_can_view_a_patients_list(patient, staff_user):
    response = client_as(staff_user).get(f"/patients/{patient.pk}/appointments")
    assert response.status_code == 200


# ---------- real JWT login ----------


def test_jwt_login_flow(doctor, hours, patient):
    client = APIClient()
    token = client.post(
        "/auth/token",
        {"username": patient.user.username, "password": "TestPass123!"},
        format="json",
    )
    assert token.status_code == 200

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.json()['access']}")
    response = client.get(
        f"/doctors/{doctor.pk}/availability", {"date": DAY.isoformat()}
    )
    assert response.status_code == 200


def reschedule(user, appointment_id, start):
    return client_as(user).patch(
        f"/appointments/{appointment_id}/reschedule",
        {"start_time": iso(start)},
        format="json",
    )


def test_reschedule_into_a_taken_slot_returns_409(
    doctor, hours, patient, other_patient
):
    mine = book(patient.user, doctor, at(9)).json()["id"]
    book(other_patient.user, doctor, at(10))
    response = reschedule(patient.user, mine, at(10))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_unavailable"


def test_reschedule_off_grid_returns_400(doctor, hours, patient):
    mine = book(patient.user, doctor, at(9)).json()["id"]
    response = reschedule(patient.user, mine, at(10, 15))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "booking_rule_violation"


def test_other_patient_cannot_reschedule(doctor, hours, patient, other_patient):
    mine = book(patient.user, doctor, at(9)).json()["id"]
    assert reschedule(other_patient.user, mine, at(10)).status_code == 404


def test_doctor_role_cannot_reschedule(doctor, hours, patient):
    mine = book(patient.user, doctor, at(9)).json()["id"]
    assert reschedule(doctor.user, mine, at(10)).status_code == 403


def test_reschedule_unknown_appointment_returns_404(patient):
    assert reschedule(patient.user, 99999, at(10)).status_code == 404


def test_booking_with_unknown_doctor_returns_400(patient):
    response = client_as(patient.user).post(
        "/appointments",
        {"doctor_id": 99999, "start_time": iso(at(9))},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_past_appointment_cannot_be_cancelled_over_http(doctor, patient):
    past = Appointment.objects.create(
        patient=patient, doctor=doctor, start_time=timezone.now() - timedelta(days=3)
    )
    response = client_as(patient.user).patch(
        f"/appointments/{past.pk}/cancel", {"reason": "Too late"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
