from django.contrib import admin

from .models import Doctor, DoctorWorkingHour


class DoctorWorkingHourInline(admin.TabularInline):
    model = DoctorWorkingHour
    extra = 0
    max_num = 7


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_username",
        "get_email",
        "get_full_name",
        "specialization",
        "is_active",
    )
    list_select_related = ("user",)
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "specialization",
    )
    inlines = [DoctorWorkingHourInline]

    @admin.display(description="Username")
    def get_username(self, obj):
        return obj.user.username

    @admin.display(description="Email")
    def get_email(self, obj):
        return obj.user.email

    @admin.display(description="Full Name")
    def get_full_name(self, obj):
        return obj.user.get_full_name()
