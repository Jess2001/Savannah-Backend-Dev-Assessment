import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_create_superuser_has_staff_role():
    user = User.objects.create_superuser(
        username="admin_test",
        email="admin@example.com",
        password="TestPassword123!",
    )

    assert user.role == User.Role.STAFF
    assert user.is_superuser is True
    assert user.is_staff is True


@pytest.mark.django_db
def test_create_user_defaults_to_patient_role():
    user = User.objects.create_user(
        username="patient_test",
        email="patient@example.com",
        password="TestPassword123!",
    )

    assert user.role == User.Role.PATIENT
    assert user.is_superuser is False
    assert user.is_staff is False
