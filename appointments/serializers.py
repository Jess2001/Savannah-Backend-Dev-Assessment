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


class BookAppointmentSerializer(serializers.Serializer):
    doctor_id = serializers.PrimaryKeyRelatedField(
        source="doctor", queryset=Doctor.objects.all()
    )
    start_time = StrictDateTimeField()


class RescheduleSerializer(serializers.Serializer):
    start_time = StrictDateTimeField()


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField()


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

    def get_doctor_name(self, obj):
        return str(obj.doctor)

    def get_local_start_time(self, obj):
        return to_clinic_time(obj.start_time).isoformat()
