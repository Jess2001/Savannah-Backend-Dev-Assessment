from rest_framework.permissions import BasePermission


class IsPatient(BasePermission):
    """Authenticated user with the PATIENT role and a patient profile."""

    message = "Only patients can perform this action."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == user.Role.PATIENT
            and hasattr(user, "patient_profile")
        )


class IsPatientOrStaff(BasePermission):
    """Patients (with a profile) and staff. Doctors have no appointment access yet."""

    message = "You do not have access to appointments."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role == user.Role.STAFF:
            return True
        return user.role == user.Role.PATIENT and hasattr(user, "patient_profile")
