from io import StringIO

import pytest
from django.core.management import call_command

from doctors.models import Doctor, DoctorWorkingHour
from patients.models import Patient


@pytest.mark.django_db
def test_seed_demo_is_idempotent():
    call_command("seed_demo", stdout=StringIO())
    call_command("seed_demo", stdout=StringIO())

    assert Doctor.objects.count() == 5
    assert Patient.objects.count() == 2
    assert DoctorWorkingHour.objects.count() == 23  # 3x5 + 3 + 5
