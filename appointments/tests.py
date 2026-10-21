from datetime import datetime, timezone

import pytest
from django.db import IntegrityError, transaction

from appointments.models import Appointment, AppointmentStatus

pytestmark = pytest.mark.django_db

SLOT = datetime(2030, 1, 7, 6, 0, tzinfo=timezone.utc)


def make_appointment(patient, doctor, start=SLOT, **extra):
    return Appointment.objects.create(
        patient=patient, doctor=doctor, start_time=start, **extra
    )


def test_two_patients_cannot_confirm_same_doctor_slot(doctor, patient, other_patient):
    make_appointment(patient, doctor)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_appointment(other_patient, doctor)


def test_patient_cannot_confirm_two_doctors_at_same_time(doctor, other_doctor, patient):
    make_appointment(patient, doctor)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_appointment(patient, other_doctor)


def test_cancelled_appointment_does_not_block_the_slot(doctor, patient, other_patient):
    make_appointment(
        patient,
        doctor,
        status=AppointmentStatus.CANCELLED,
        cancellation_reason="Unwell",
    )
    make_appointment(other_patient, doctor)


def test_cancelled_appointment_requires_a_reason(doctor, patient):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_appointment(patient, doctor, status=AppointmentStatus.CANCELLED)


def test_end_time_is_thirty_minutes_after_start(doctor, patient):
    appt = make_appointment(patient, doctor)
    assert (appt.end_time - appt.start_time).total_seconds() == 1800
