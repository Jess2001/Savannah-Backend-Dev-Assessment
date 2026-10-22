from django.utils import timezone
from rest_framework import serializers

from doctors.models import Doctor

from .availability import to_clinic_time
from .models import Appointment


class StrictDateTimeField(serializers.DateTimeField):
    """A datetime that must carry a timezone.

    By default DRF silently assumes UTC for a datetime without an offset.
    For a booking system, "09:00" with no timezone is ambiguous, so reject it.
    """

    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError(
                "Include a timezone offset, for example 2030-01-07T06:00:00Z."
            )
        return super().enforce_timezone(value)


START_TIME_HELP = (
    "Slot start, ISO 8601 with a timezone, on the :00 or :30 grid. "
    "Example: 2026-10-26T06:00:00Z (09:00 in Nairobi)."
)


class BookAppointmentSerializer(serializers.Serializer):
    doctor_id = serializers.PrimaryKeyRelatedField(
        source="doctor",
        queryset=Doctor.objects.all(),
        help_text="Id of the doctor to book.",
    )
    start_time = StrictDateTimeField(help_text=START_TIME_HELP)


class RescheduleSerializer(serializers.Serializer):
    start_time = StrictDateTimeField(help_text=START_TIME_HELP)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500, help_text="Why the appointment is being cancelled (required)."
    )


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField(
        help_text="Clinic-local date, YYYY-MM-DD (Africa/Nairobi)."
    )


class AppointmentSerializer(serializers.ModelSerializer):
    """Output-only representation of an appointment."""

    doctor_id = serializers.IntegerField(read_only=True)
    patient_id = serializers.IntegerField(read_only=True)
    doctor_name = serializers.SerializerMethodField()
    end_time = serializers.DateTimeField(read_only=True)
    local_start_time = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "doctor_id",
            "doctor_name",
            "patient_id",
            "start_time",
            "end_time",
            "local_start_time",
            "status",
            "cancellation_reason",
            "created_at",
        ]

    def get_doctor_name(self, obj) -> str:
        return str(obj.doctor)

    def get_local_start_time(self, obj) -> str:
        return to_clinic_time(obj.start_time).isoformat()


# --- Documentation-only shapes (the views build these dicts by hand) ---


class SlotSerializer(serializers.Serializer):
    start_time = serializers.DateTimeField(help_text="Slot start in UTC.")
    end_time = serializers.DateTimeField(help_text="Slot end in UTC.")
    local_start_time = serializers.CharField(help_text="Slot start in clinic time.")


class AvailabilitySerializer(serializers.Serializer):
    doctor_id = serializers.IntegerField()
    date = serializers.DateField()
    timezone = serializers.CharField()
    slots = SlotSerializer(many=True)


class ErrorBodySerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable machine-readable error code.")
    message = serializers.CharField(help_text="Human-readable explanation.")
    details = serializers.JSONField(
        required=False, help_text="Per-field errors, if any."
    )


class ErrorResponseSerializer(serializers.Serializer):
    error = ErrorBodySerializer()
