from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from doctors.models import Doctor
from patients.models import Patient

from . import services
from .availability import get_available_slots, to_clinic_time
from .constants import SLOT_DURATION
from .models import Appointment, AppointmentStatus
from .permissions import IsPatient, IsPatientOrStaff
from .serializers import (
    AppointmentSerializer,
    AvailabilityQuerySerializer,
    BookAppointmentSerializer,
    CancelSerializer,
    RescheduleSerializer,
)


def get_visible_appointment(user, pk):
    """Fetch an appointment the user is allowed to see, or raise a 404.

    Patients only see their own. Staff see everything. For anyone else's
    appointment we return 404 (not 403), so its existence isn't revealed.
    """
    queryset = Appointment.objects.filter(pk=pk)
    if user.role == user.Role.PATIENT:
        queryset = queryset.filter(patient=user.patient_profile)
    return get_object_or_404(queryset)


class BookAppointmentView(APIView):
    """POST /appointments"""

    permission_classes = [IsPatient]

    def post(self, request):
        serializer = BookAppointmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        appointment = services.book_appointment(
            patient=request.user.patient_profile,
            doctor=serializer.validated_data["doctor"],
            start_time=serializer.validated_data["start_time"],
        )
        return Response(
            AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED
        )


class DoctorAvailabilityView(APIView):
    """GET /doctors/{id}/availability?date=YYYY-MM-DD"""

    def get(self, request, pk):
        doctor = get_object_or_404(Doctor, pk=pk, is_active=True)

        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        day = query.validated_data["date"]

        slots = get_available_slots(doctor, day)
        return Response(
            {
                "doctor_id": doctor.pk,
                "date": day.isoformat(),
                "timezone": settings.CLINIC_TIMEZONE,
                "slots": [
                    {
                        "start_time": slot,
                        "end_time": slot + SLOT_DURATION,
                        "local_start_time": to_clinic_time(slot).isoformat(),
                    }
                    for slot in slots
                ],
            }
        )


class CancelAppointmentView(APIView):
    """PATCH /appointments/{id}/cancel"""

    permission_classes = [IsPatientOrStaff]

    def patch(self, request, pk):
        appointment = get_visible_appointment(request.user, pk)

        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cancelled = services.cancel_appointment(
            appointment.pk, serializer.validated_data["reason"]
        )
        return Response(AppointmentSerializer(cancelled).data)


class RescheduleAppointmentView(APIView):
    """PATCH /appointments/{id}/reschedule"""

    permission_classes = [IsPatientOrStaff]

    def patch(self, request, pk):
        appointment = get_visible_appointment(request.user, pk)

        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        moved = services.reschedule_appointment(
            appointment.pk, serializer.validated_data["start_time"]
        )
        return Response(AppointmentSerializer(moved).data)


class PatientAppointmentsView(APIView):
    """GET /patients/{id}/appointments  (upcoming, confirmed, soonest first)"""

    permission_classes = [IsPatientOrStaff]

    def get(self, request, pk):
        user = request.user
        if user.role == user.Role.PATIENT:
            if user.patient_profile.pk != pk:
                raise Http404  # someone else's history: pretend it doesn't exist
            patient = user.patient_profile
        else:
            patient = get_object_or_404(Patient, pk=pk)

        appointments = (
            Appointment.objects.filter(
                patient=patient,
                status=AppointmentStatus.CONFIRMED,
                start_time__gt=timezone.now(),
            )
            .select_related("doctor__user")
            .order_by("start_time")
        )
        return Response(AppointmentSerializer(appointments, many=True).data)
