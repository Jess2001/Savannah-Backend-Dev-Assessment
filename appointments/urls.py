from django.urls import path

from . import views

urlpatterns = [
    path("appointments", views.BookAppointmentView.as_view(), name="book-appointment"),
    path(
        "appointments/<int:pk>/cancel",
        views.CancelAppointmentView.as_view(),
        name="cancel-appointment",
    ),
    path(
        "appointments/<int:pk>/reschedule",
        views.RescheduleAppointmentView.as_view(),
        name="reschedule-appointment",
    ),
    path(
        "doctors/<int:pk>/availability",
        views.DoctorAvailabilityView.as_view(),
        name="doctor-availability",
    ),
    path(
        "patients/<int:pk>/appointments",
        views.PatientAppointmentsView.as_view(),
        name="patient-appointments",
    ),
]
