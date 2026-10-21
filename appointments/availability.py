from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from .constants import MAX_DAYS_AHEAD, MIN_NOTICE, SLOT_DURATION
from .models import Appointment, AppointmentStatus

UTC = dt_timezone.utc


def clinic_timezone():
    return ZoneInfo(settings.CLINIC_TIMEZONE)


def to_clinic_time(moment):
    """Convert any aware datetime to the clinic's local time."""
    return moment.astimezone(clinic_timezone())


def clinic_day_bounds(day):
    """Return the UTC instants where a clinic-local calendar day starts and ends."""
    tz = clinic_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def working_slots(doctor, day):
    """Every 30-minute slot start the doctor works on `day`, as UTC datetimes.

    This is the single source of truth for "is this a real slot?". Both the
    availability endpoint and the booking rules use it.
    """
    interval = doctor.working_hours.filter(weekday=day.weekday()).first()
    if interval is None:
        return []

    tz = clinic_timezone()
    current = datetime.combine(day, interval.start_time, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day, interval.end_time, tzinfo=tz).astimezone(UTC)

    slots = []
    while current + SLOT_DURATION <= end:
        slots.append(current)
        current += SLOT_DURATION
    return slots


def check_booking_window(start_time, now):
    """Return an error message if the timing rules are broken, otherwise None."""
    if start_time <= now:
        return "Appointments cannot be booked in the past."

    if start_time < now + MIN_NOTICE:
        hours = int(MIN_NOTICE.total_seconds() // 3600)
        return f"Appointments must be booked at least {hours} hour(s) in advance."

    last_allowed_day = to_clinic_time(now).date() + timedelta(days=MAX_DAYS_AHEAD)
    if to_clinic_time(start_time).date() > last_allowed_day:
        return f"Appointments can be booked at most {MAX_DAYS_AHEAD} days ahead."

    return None


def get_available_slots(doctor, day, now=None):
    """Bookable slot starts for `doctor` on the clinic-local date `day`."""
    now = now or timezone.now()
    day_start, day_end = clinic_day_bounds(day)

    # One query for the whole day, then subtract in memory (no query per slot).
    booked = set(
        Appointment.objects.filter(
            doctor=doctor,
            status=AppointmentStatus.CONFIRMED,
            start_time__gte=day_start,
            start_time__lt=day_end,
        ).values_list("start_time", flat=True)
    )

    return [
        slot
        for slot in working_slots(doctor, day)
        if slot not in booked and check_booking_window(slot, now) is None
    ]
