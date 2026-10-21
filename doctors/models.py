from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from appointments.constants import SLOT_MINUTES


class Doctor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        help_text="Link to the underlying Django authentication user record.",
    )
    specialization = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.user_id and self.user.role != self.user.Role.DOCTOR:
            raise ValidationError({"user": "Linked user must have the DOCTOR role."})

    def __str__(self):
        return f"Dr. {self.user.get_full_name() or self.user.username}"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class DoctorWorkingHour(models.Model):
    """One working interval for one doctor on one weekday (e.g. Monday 08:00-17:00).

    A weekday with no row means the doctor does not work that day.
    """

    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.CASCADE,
        related_name="working_hours",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["doctor", "weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "weekday"],
                name="uniq_doctor_weekday_working_hours",
            ),
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="working_hours_end_after_start",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        for field in ("start_time", "end_time"):
            value = getattr(self, field)
            if value is None:
                continue
            on_grid = (
                value.minute % SLOT_MINUTES == 0
                and value.second == 0
                and value.microsecond == 0
            )
            if not on_grid:
                errors.setdefault(field, []).append(
                    f"Must fall on a {SLOT_MINUTES}-minute boundary (:00 or :30)."
                )

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            errors.setdefault("end_time", []).append(
                "End time must be later than start time."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.doctor} - {self.get_weekday_display()} "
            f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        )
