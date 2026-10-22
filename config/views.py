from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class HealthView(PublicView):
    """Liveness check for the host. Deliberately does NOT query the database,
    so health checks never keep the (scale-to-zero) database awake."""

    @extend_schema(exclude=True)
    def get(self, request):
        return Response({"status": "ok"})


class ApiRootView(PublicView):
    @extend_schema(exclude=True)
    def get(self, request):
        return Response(
            {
                "service": "Savannah Clinic Appointment API",
                "docs": "/docs",
                "health": "/health",
                "login": "POST /auth/token",
                "endpoints": [
                    "POST /appointments",
                    "GET /doctors/{id}/availability?date=YYYY-MM-DD",
                    "PATCH /appointments/{id}/cancel",
                    "PATCH /appointments/{id}/reschedule",
                    "GET /patients/{id}/appointments",
                ],
            }
        )
