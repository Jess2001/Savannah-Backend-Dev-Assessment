from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    """Create superusers with the correct application role."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = self.model.Role.STAFF

        return super().create_superuser(
            username=username,
            email=email,
            password=password,
            **extra_fields,
        )


class User(AbstractUser):
    class Role(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        DOCTOR = "DOCTOR", "Doctor"
        STAFF = "STAFF", "Staff"

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.PATIENT,
    )

    objects = UserManager()

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
