import pytest
from django.contrib.auth import get_user_model

from doctors.models import Doctor
from patients.models import Patient

User = get_user_model()


def _make_doctor(username):
    user = User.objects.create_user(
        username=username, password="TestPass123!", role=User.Role.DOCTOR
    )
    return Doctor.objects.create(user=user, specialization="General")


def _make_patient(username):
    user = User.objects.create_user(username=username, password="TestPass123!")
    return Patient.objects.create(user=user)


@pytest.fixture
def doctor(db):
    return _make_doctor("dr_one")


@pytest.fixture
def other_doctor(db):
    return _make_doctor("dr_two")


@pytest.fixture
def patient(db):
    return _make_patient("patient_one")


@pytest.fixture
def other_patient(db):
    return _make_patient("patient_two")
