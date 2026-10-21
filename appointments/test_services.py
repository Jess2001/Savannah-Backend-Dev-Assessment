from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from appointments import services
from appointments.availability import get_available_slots
from appointments.exceptions import (
    BookingValidationError,
    InvalidStateError,
    SlotUnavailableError,
)
from appointments.models import Appointment, AppointmentStatus
from doctors.models import DoctorWorkingHour, Weekday
import threading

from django.db import connections

pytestmark = pytest.mark.django_db

NAIROBI = ZoneInfo("Africa/Nairobi")
MONDAY = date(2030, 1, 7)
NOW = datetime(2030, 1, 6, 6, 0, tzinfo=timezone.utc)  # Sunday 09:00 Nairobi


def at(hour, minute=0, day=MONDAY):
    """A clinic-local time, returned as the UTC instant that gets stored."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=NAIROBI)
    return local.astimezone(timezone.utc)


def set_hours(doctor, weekday=Weekday.MONDAY, start=time(8, 0), end=time(17, 0)):
    return DoctorWorkingHour.objects.create(
        doctor=doctor, weekday=weekday, start_time=start, end_time=end
    )


@pytest.fixture
def hours(doctor):
    return set_hours(doctor)


def book(patient, doctor, start, now=NOW):
    return services.book_appointment(patient, doctor, start, now=now)


# ---------- availability ----------


def test_monday_has_eighteen_slots(doctor, hours):
    slots = get_available_slots(doctor, MONDAY, now=NOW)
    assert len(slots) == 18
    assert slots[0] == at(8)
    assert slots[-1] == at(16, 30)


def test_booked_slot_is_not_available(doctor, hours, patient):
    book(patient, doctor, at(9))
    assert at(9) not in get_available_slots(doctor, MONDAY, now=NOW)


def test_day_off_has_no_slots(doctor, hours):
    assert get_available_slots(doctor, date(2030, 1, 8), now=NOW) == []  # Tuesday


def test_past_date_has_no_slots(doctor, hours):
    assert get_available_slots(doctor, MONDAY, now=at(18)) == []


def test_slots_inside_notice_window_are_hidden(doctor, hours):
    slots = get_available_slots(doctor, MONDAY, now=at(8, 30))
    assert slots[0] == at(9, 30)


# ---------- booking ----------


def test_book_valid_slot(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    assert appt.status == AppointmentStatus.CONFIRMED
    assert appt.start_time == at(9)


def test_off_grid_time_is_rejected(doctor, hours, patient, other_patient):
    book(patient, doctor, at(8))
    with pytest.raises(BookingValidationError, match="30-minute"):
        book(other_patient, doctor, at(8, 15))


@pytest.mark.parametrize("hour, minute", [(7, 30), (17, 0), (23, 0)])
def test_outside_working_hours_is_rejected(doctor, hours, patient, hour, minute):
    with pytest.raises(BookingValidationError, match="does not work"):
        book(patient, doctor, at(hour, minute))


def test_last_slot_of_the_day_is_bookable(doctor, hours, patient):
    book(patient, doctor, at(16, 30))


def test_booking_in_the_past_is_rejected(doctor, hours, patient):
    with pytest.raises(BookingValidationError, match="past"):
        book(patient, doctor, at(9), now=at(10))


def test_less_than_one_hour_notice_is_rejected(doctor, hours, patient):
    with pytest.raises(BookingValidationError, match="in advance"):
        book(patient, doctor, at(9), now=at(8, 1))


def test_exactly_one_hour_notice_is_allowed(doctor, hours, patient):
    book(patient, doctor, at(9), now=at(8))


def test_sixty_day_horizon_boundary(doctor, patient):
    set_hours(doctor, Weekday.FRIDAY)
    set_hours(doctor, Weekday.SATURDAY)
    now = at(9)  # Monday 7 Jan 2030; 60 days later is Friday 8 March
    book(patient, doctor, at(10, day=date(2030, 3, 8)), now=now)
    with pytest.raises(BookingValidationError, match="days ahead"):
        book(patient, doctor, at(10, day=date(2030, 3, 9)), now=now)


def test_second_patient_cannot_take_a_booked_slot(
    doctor, hours, patient, other_patient
):
    book(patient, doctor, at(9))
    with pytest.raises(SlotUnavailableError):
        book(other_patient, doctor, at(9))


def test_patient_cannot_book_two_doctors_at_the_same_time(
    doctor, other_doctor, hours, patient
):
    set_hours(other_doctor)
    book(patient, doctor, at(9))
    with pytest.raises(SlotUnavailableError, match="already have"):
        book(patient, other_doctor, at(9))


def test_inactive_doctor_cannot_be_booked(doctor, hours, patient):
    doctor.is_active = False
    doctor.save()
    with pytest.raises(BookingValidationError):
        book(patient, doctor, at(9))


def test_database_conflict_is_translated_to_a_clean_error(
    doctor, hours, patient, other_patient, monkeypatch
):
    book(patient, doctor, at(9))
    # Simulate the race: skip the friendly checks so the database has to decide.
    monkeypatch.setattr(services, "validate_slot", lambda *args, **kwargs: None)
    with pytest.raises(SlotUnavailableError, match="just been booked"):
        book(other_patient, doctor, at(9))


# ---------- cancel ----------


def test_cancel_frees_the_slot(doctor, hours, patient, other_patient):
    appt = book(patient, doctor, at(9))
    services.cancel_appointment(appt.pk, "Feeling better")

    appt.refresh_from_db()
    assert appt.status == AppointmentStatus.CANCELLED
    assert appt.cancellation_reason == "Feeling better"
    assert at(9) in get_available_slots(doctor, MONDAY, now=NOW)
    book(other_patient, doctor, at(9))  # the slot can be rebooked


def test_cancel_requires_a_reason(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    with pytest.raises(BookingValidationError, match="reason"):
        services.cancel_appointment(appt.pk, "   ")


def test_cancel_twice_is_a_conflict(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    services.cancel_appointment(appt.pk, "First")
    with pytest.raises(InvalidStateError, match="already cancelled"):
        services.cancel_appointment(appt.pk, "Second")


def test_completed_appointment_cannot_be_cancelled(doctor, patient):
    appt = Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        start_time=at(9),
        status=AppointmentStatus.COMPLETED,
    )
    with pytest.raises(InvalidStateError, match="Only confirmed"):
        services.cancel_appointment(appt.pk, "Changed my mind")


# ---------- reschedule ----------


def test_reschedule_moves_appointment_and_frees_old_slot(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    services.reschedule_appointment(appt.pk, at(10), now=NOW)

    appt.refresh_from_db()
    assert appt.start_time == at(10)
    slots = get_available_slots(doctor, MONDAY, now=NOW)
    assert at(9) in slots
    assert at(10) not in slots


def test_failed_reschedule_keeps_the_original_slot(
    doctor, hours, patient, other_patient
):
    appt = book(patient, doctor, at(9))
    book(other_patient, doctor, at(10))
    with pytest.raises(SlotUnavailableError):
        services.reschedule_appointment(appt.pk, at(10), now=NOW)

    appt.refresh_from_db()
    assert appt.start_time == at(9)
    assert appt.status == AppointmentStatus.CONFIRMED


def test_reschedule_to_same_time_is_rejected(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    with pytest.raises(BookingValidationError, match="already at that time"):
        services.reschedule_appointment(appt.pk, at(9), now=NOW)


def test_cancelled_appointment_cannot_be_rescheduled(doctor, hours, patient):
    appt = book(patient, doctor, at(9))
    services.cancel_appointment(appt.pk, "Cannot make it")
    with pytest.raises(InvalidStateError, match="cancelled"):
        services.reschedule_appointment(appt.pk, at(10), now=NOW)


def test_reschedule_follows_the_notice_rule(doctor, hours, patient):
    appt = book(patient, doctor, at(15))
    with pytest.raises(BookingValidationError, match="in advance"):
        services.reschedule_appointment(appt.pk, at(9), now=at(8, 30))


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_bookings_have_exactly_one_winner(
    doctor, hours, patient, other_patient
):
    results = []
    start_together = threading.Barrier(2)

    def attempt(who):
        try:
            start_together.wait()
            book(who, doctor, at(9))
            results.append("booked")
        except SlotUnavailableError:
            results.append("conflict")
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=attempt, args=(patient,)),
        threading.Thread(target=attempt, args=(other_patient,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["booked", "conflict"]
    assert (
        Appointment.objects.filter(
            doctor=doctor, start_time=at(9), status=AppointmentStatus.CONFIRMED
        ).count()
        == 1
    )
