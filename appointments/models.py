from django.db import models
from django.db.models import Q

from .constants import SLOT_DURATION


class AppointmentStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"
    NO_SHOW = "NO_SHOW", "No show"


class Appointment(models.Model):
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    doctor = models.ForeignKey(
        "doctors.Doctor",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    start_time = models.DateTimeField(
        help_text="Start of the 30-minute slot, stored in UTC."
    )
    status = models.CharField(
        max_length=10,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.CONFIRMED,
    )
    cancellation_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "start_time"],
                condition=Q(status=AppointmentStatus.CONFIRMED),
                name="uniq_confirmed_doctor_slot",
            ),
            models.UniqueConstraint(
                fields=["patient", "start_time"],
                condition=Q(status=AppointmentStatus.CONFIRMED),
                name="uniq_confirmed_patient_slot",
            ),
            models.CheckConstraint(
                condition= ~Q(status=AppointmentStatus.CANCELLED)
                | ~Q(cancellation_reason=""),
                name="cancelled_requires_reason",
            ),
        ]

    @property
    def end_time(self):
        return self.start_time + SLOT_DURATION

    def __str__(self):
        return f"{self.patient} with {self.doctor} at {self.start_time:%Y-%m-%d %H:%M} UTC ({self.status})"
