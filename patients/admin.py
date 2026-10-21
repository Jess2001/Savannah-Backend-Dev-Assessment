from django.contrib import admin
from .models import Patient
# Register your models here.
@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("id", "get_username", "get_email", "get_full_name")
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    list_select_related = ("user",)
    # Helper methods to display details from the linked User model cleanly
    @admin.display(description="Username")
    def get_username(self, obj):
        return obj.user.username
    @admin.display(description="Email")
    def get_email(self, obj):
        return obj.user.email
    @admin.display(description="Full Name")
    def get_full_name(self, obj):
        return obj.user.get_full_name()
