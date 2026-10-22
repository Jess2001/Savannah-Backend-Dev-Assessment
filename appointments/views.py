from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
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
    AvailabilitySerializer,
    BookAppointmentSerializer,
    CancelSerializer,
    ErrorResponseSerializer,
    RescheduleSerializer,
)

ERROR_DESCRIPTIONS = {
    400: "Invalid request or a booking rule was broken (off-grid time, outside hours, past, under 1 hour notice, beyond 60 days...).",
    401: "Missing or invalid access token.",
    403: "Your role is not allowed to do this.",
    404: "Not found, or not yours.",
    409: "Slot already taken, or the appointment's status does not allow this.",
}


def error_responses(*codes):
    return {
        code: OpenApiResponse(
            ErrorResponseSerializer, description=ERROR_DESCRIPTIONS[code]
        )
        for code in codes
    }


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

    @extend_schema(
        tags=["Appointments"],
        summary="Book an appointment",
        description=(
            "Books a 30-minute slot for the authenticated **patient**. "
            "Rules: start on the :00/:30 grid, inside the doctor's working hours, "
            "at least 1 hour from now, at most 60 days ahead, and neither the doctor "
            "nor the patient may already have a confirmed appointment then."
        ),
        request=BookAppointmentSerializer,
        responses={201: AppointmentSerializer, **error_responses(400, 401, 403, 409)},
        examples=[
            OpenApiExample(
                "Book 09:00 Nairobi time",
                value={"doctor_id": 1, "start_time": "2026-10-26T06:00:00Z"},
                request_only=True,
            )
        ],
    )
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

    @extend_schema(
        tags=["Doctors"],
        summary="List a doctor's free slots for a date",
        description=(
            "Returns every bookable 30-minute slot for the clinic-local date. "
            "A past date, a day off, or a date beyond 60 days returns an empty list. "
            "Inactive or unknown doctors return 404. Any authenticated user may call this."
        ),
        parameters=[AvailabilityQuerySerializer],
        responses={200: AvailabilitySerializer, **error_responses(400, 401, 404)},
    )
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

    @extend_schema(
        tags=["Appointments"],
        summary="Cancel an appointment",
        description=(
            "Cancels a **confirmed** appointment and frees its slot. A reason is required. "
            "Patients can cancel their own; staff can cancel any. "
            "Cancelling twice returns 409."
        ),
        request=CancelSerializer,
        responses={
            200: AppointmentSerializer,
            **error_responses(400, 401, 403, 404, 409),
        },
        examples=[
            OpenApiExample(
                "Cancel with a reason",
                value={"reason": "Feeling better, no longer need the visit"},
                request_only=True,
            )
        ],
    )
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

    @extend_schema(
        tags=["Appointments"],
        summary="Move an appointment to a new slot",
        description=(
            "Moves a **confirmed** appointment. The new slot is validated exactly like "
            "a fresh booking; if it fails, the original stays unchanged. The old slot "
            "becomes bookable again. Cancelled appointments cannot be rescheduled (409)."
        ),
        request=RescheduleSerializer,
        responses={
            200: AppointmentSerializer,
            **error_responses(400, 401, 403, 404, 409),
        },
        examples=[
            OpenApiExample(
                "Move to 10:00 Nairobi time",
                value={"start_time": "2026-10-26T07:00:00Z"},
                request_only=True,
            )
        ],
    )
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

    @extend_schema(
        tags=["Patients"],
        summary="A patient's upcoming appointments",
        description=(
            "Confirmed, future appointments sorted soonest first. Patients can only "
            "view their own list (another patient's id returns 404); staff can view any."
        ),
        responses={
            200: AppointmentSerializer(many=True),
            **error_responses(401, 403, 404),
        },
    )
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
