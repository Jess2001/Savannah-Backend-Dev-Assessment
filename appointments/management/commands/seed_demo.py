from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from doctors.models import Doctor, DoctorWorkingHour, Weekday
from patients.models import Patient

User = get_user_model()

MON_FRI = [
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
]

# username, first name, last name, specialization, weekdays, start, end
DOCTORS = [
    (
        "dr_amina",
        "Amina",
        "Hassan",
        "General Practice",
        MON_FRI,
        time(8, 0),
        time(17, 0),
    ),
    ("dr_brian", "Brian", "Otieno", "Pediatrics", MON_FRI, time(8, 0), time(17, 0)),
    (
        "dr_cynthia",
        "Cynthia",
        "Wanjiru",
        "Dermatology",
        MON_FRI,
        time(8, 0),
        time(17, 0),
    ),
    (
        "dr_david",
        "David",
        "Kamau",
        "Cardiology",
        [Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY],
        time(9, 0),
        time(15, 0),
    ),
    (
        "dr_esther",
        "Esther",
        "Mwangi",
        "Gynecology",
        [
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
            Weekday.SATURDAY,
        ],
        time(10, 0),
        time(18, 0),
    ),
]

PATIENTS = [
    ("patient_one", "Peter", "Njoroge"),
    ("patient_two", "Mary", "Achieng"),
]


class Command(BaseCommand):
    help = "Create demo doctors, patients, staff and working hours. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="ClinicDemo123!")

    def _user(self, username, first, last, role, password):
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User(username=username, first_name=first, last_name=last, role=role)
            user.set_password(password)  # hashes it; never store a raw password
            user.save()
        return user

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]

        self._user("staff_demo", "Sam", "Staff", User.Role.STAFF, password)

        for username, first, last, specialization, days, start, end in DOCTORS:
            user = self._user(username, first, last, User.Role.DOCTOR, password)
            doctor, _ = Doctor.objects.get_or_create(
                user=user, defaults={"specialization": specialization}
            )
            for day in days:
                DoctorWorkingHour.objects.update_or_create(
                    doctor=doctor,
                    weekday=day,
                    defaults={"start_time": start, "end_time": end},
                )

        for username, first, last in PATIENTS:
            user = self._user(username, first, last, User.Role.PATIENT, password)
            Patient.objects.get_or_create(user=user)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"Logins (password: {password}):")
        self.stdout.write("  patients: patient_one, patient_two")
        self.stdout.write("  staff:    staff_demo")
        self.stdout.write("  doctors:  " + ", ".join(row[0] for row in DOCTORS))
