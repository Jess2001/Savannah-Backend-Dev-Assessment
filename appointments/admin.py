from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "doctor", "start_time", "status")
    list_filter = ("status", "doctor")
    list_select_related = ("patient__user", "doctor__user")
