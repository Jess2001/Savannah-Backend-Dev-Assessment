from datetime import time

import pytest
from django.core.exceptions import ValidationError

from doctors.models import DoctorWorkingHour, Weekday

pytestmark = pytest.mark.django_db


def hours(doctor, start, end, weekday=Weekday.MONDAY):
    return DoctorWorkingHour(
        doctor=doctor, weekday=weekday, start_time=start, end_time=end
    )


def test_valid_working_hours_pass(doctor):
    hours(doctor, time(8, 0), time(17, 0)).full_clean()


def test_off_grid_start_is_rejected(doctor):
    with pytest.raises(ValidationError):
        hours(doctor, time(8, 15), time(17, 0)).full_clean()


def test_end_must_be_after_start(doctor):
    with pytest.raises(ValidationError):
        hours(doctor, time(17, 0), time(8, 0)).full_clean()


def test_only_one_interval_per_weekday(doctor):
    hours(doctor, time(8, 0), time(12, 0)).save()
    with pytest.raises(ValidationError):
        hours(doctor, time(13, 0), time(17, 0)).full_clean()


def test_same_hours_on_different_weekdays_are_allowed(doctor):
    hours(doctor, time(8, 0), time(12, 0), Weekday.MONDAY).save()
    hours(doctor, time(8, 0), time(12, 0), Weekday.TUESDAY).full_clean()
