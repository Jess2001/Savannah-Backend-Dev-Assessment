from django.db import IntegrityError, transaction
from django.utils import timezone

from .availability import check_booking_window, to_clinic_time, working_slots
from .constants import SLOT_MINUTES
from .exceptions import (
    BookingValidationError,
    InvalidStateError,
    SlotUnavailableError,
)
from .models import Appointment, AppointmentStatus

# Maps a database constraint name to the message the patient should see.
CONSTRAINT_MESSAGES = {
    "uniq_confirmed_doctor_slot": (
        "That slot has just been booked by someone else. Please choose another."
    ),
    "uniq_confirmed_patient_slot": "You already have an appointment at this time.",
}


def _ensure_aware(moment):
    if timezone.is_naive(moment):
        raise BookingValidationError(
            "start_time must include a timezone, for example 2030-01-07T06:00:00Z."
        )


def _conflict_message(exc):
    """Return our message if this IntegrityError is one of our two slot constraints."""
    diag = getattr(exc.__cause__, "diag", None)
    constraint = getattr(diag, "constraint_name", None)
    return CONSTRAINT_MESSAGES.get(constraint)


def validate_slot(doctor, patient, start_time, now, ignore=None):
    """Run every booking rule. Raises a BookingError if any rule fails.

    `ignore` is the appointment being rescheduled, so it never conflicts
    with its own current slot.
    """
    _ensure_aware(start_time)

    if not doctor.is_active:
        raise BookingValidationError("This doctor is not accepting appointments.")

    local = to_clinic_time(start_time)
    if local.minute % SLOT_MINUTES != 0 or local.second or local.microsecond:
        raise BookingValidationError(
            f"Start time must be on a {SLOT_MINUTES}-minute boundary (:00 or :30)."
        )

    message = check_booking_window(start_time, now)
    if message:
        raise BookingValidationError(message)

    if start_time not in working_slots(doctor, local.date()):
        raise BookingValidationError("The doctor does not work at the requested time.")

    conflicts = Appointment.objects.filter(
        status=AppointmentStatus.CONFIRMED, start_time=start_time
    )
    if ignore is not None:
        conflicts = conflicts.exclude(pk=ignore.pk)

    if conflicts.filter(doctor=doctor).exists():
        raise SlotUnavailableError("This slot is already booked.")
    if conflicts.filter(patient=patient).exists():
        raise SlotUnavailableError("You already have an appointment at this time.")


def book_appointment(patient, doctor, start_time, now=None):
    now = now or timezone.now()
    validate_slot(doctor, patient, start_time, now)

    try:
        # The inner transaction makes a failed insert roll back cleanly
        # without breaking any transaction the caller is already in.
        with transaction.atomic():
            return Appointment.objects.create(
                patient=patient, doctor=doctor, start_time=start_time
            )
    except IntegrityError as exc:
        message = _conflict_message(exc)
        if message is None:
            raise  # not one of our constraints: a real bug, don't hide it
        raise SlotUnavailableError(message) from exc


def cancel_appointment(appointment_id, reason, now=None):
    now = now or timezone.now()
    reason = (reason or "").strip()
    if not reason:
        raise BookingValidationError("A cancellation reason is required.")

    with transaction.atomic():
        appointment = Appointment.objects.select_for_update().get(pk=appointment_id)

        if appointment.status == AppointmentStatus.CANCELLED:
            raise InvalidStateError("This appointment is already cancelled.")
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise InvalidStateError(
                "Only confirmed appointments can be cancelled "
                f"(this one is {appointment.get_status_display().lower()})."
            )
        if appointment.start_time <= now:
            raise InvalidStateError(
                "This appointment has already started or passed and can no longer be cancelled."
            )
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancellation_reason = reason
        appointment.save(update_fields=["status", "cancellation_reason", "updated_at"])

    return appointment


def reschedule_appointment(appointment_id, new_start_time, now=None):
    now = now or timezone.now()
    _ensure_aware(new_start_time)

    with transaction.atomic():
        appointment = (
            Appointment.objects.select_for_update(of=("self",))
            .select_related("doctor", "patient")
            .get(pk=appointment_id)
        )

        if appointment.status == AppointmentStatus.CANCELLED:
            raise InvalidStateError("A cancelled appointment cannot be rescheduled.")
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise InvalidStateError(
                "Only confirmed appointments can be rescheduled "
                f"(this one is {appointment.get_status_display().lower()})."
            )
        if appointment.start_time <= now:
            raise InvalidStateError(
                "This appointment has already started or passed and can no longer be rescheduled."
            )
        if appointment.start_time == new_start_time:
            raise BookingValidationError("The appointment is already at that time.")

        validate_slot(
            appointment.doctor,
            appointment.patient,
            new_start_time,
            now,
            ignore=appointment,
        )

        appointment.start_time = new_start_time
        try:
            with transaction.atomic():
                appointment.save(update_fields=["start_time", "updated_at"])
        except IntegrityError as exc:
            message = _conflict_message(exc)
            if message is None:
                raise
            raise SlotUnavailableError(message) from exc

    return appointment
