
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from patients.models import Patient

User = get_user_model()


@pytest.mark.django_db
def test_patient_rejects_non_patient_role():
    user = User.objects.create_user(username="d1", password="x", role=User.Role.DOCTOR)
    with pytest.raises(ValidationError):
        Patient(user=user).full_clean()


@pytest.mark.django_db
def test_patient_accepts_patient_role():
    user = User.objects.create_user(username="p1", password="x")
    Patient(user=user).full_clean()
