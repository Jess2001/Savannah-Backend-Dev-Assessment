# Savannah Clinic Appointment API

A REST API for managing doctor availability and patient appointments at a small clinic. Built with Python, Django REST Framework, and PostgreSQL.

## Project status

**Overall status: Designed; implementation in progress.**

Use these labels throughout development:

- **Designed:** The decision or behavior has been agreed upon.
- **Implemented:** The corresponding code exists.
- **Verified:** Automated tests or deployment checks demonstrate the behavior.

Planned functionality is not considered implemented or verified until the code and tests support the claim.

## 1. Problem and scope

The clinic has five doctors. Each doctor has recurring working hours, and appointments use fixed 30-minute slots.

The API will allow authenticated users to retrieve doctor availability, book appointments, cancel bookings, and reschedule appointments. Patients can also retrieve their upcoming appointments.

The initial implementation prioritizes correctness, clear business rules, database integrity, testability, and straightforward deployment.

## 2. Technology stack

- Python 3.11
- Django 5.2
- Django REST Framework
- PostgreSQL 16
- pytest and pytest-django
- GitHub Actions for continuous integration
- Cloud deployment provider to be finalized after verifying current hosting requirements

## 3. Architecture

The application uses separate Django apps for distinct responsibilities:

- **accounts:** Custom user model, application roles, and authentication.
- **patients:** Patient profiles and patient-specific information.
- **doctors:** Doctor profiles and recurring working hours.
- **appointments:** Appointment lifecycle, availability generation, validation, and booking operations.

Business rules will live in reusable application services rather than being duplicated across API views. Serializers will validate request data, views will handle HTTP behavior and permissions, and database constraints will provide a final layer of integrity protection.

### Data model

**User**
- Django authentication fields.
- Application role: `PATIENT`, `DOCTOR`, or `STAFF`.
- Django's `is_staff` and superuser permissions remain separate from the application role.

**Patient**
- One-to-one relationship with a user.
- Patient-specific profile information.

**Doctor**
- One-to-one relationship with a user.
- Doctor profile and active status.

**DoctorWorkingHour**
- Foreign key to a doctor.
- Day of the week.
- Start and end times for a working interval.
- Multiple intervals per day are supported for split shifts.

**Appointment**
- Foreign key to a patient.
- Foreign key to a doctor.
- Timezone-aware start timestamp stored in UTC.
- Status: `CONFIRMED` or `CANCELLED`.
- Cancellation reason and creation/update timestamps.

Appointment duration is fixed at 30 minutes. The end time is derived from the start time rather than stored independently.

Cancelled appointments remain in the database for history but no longer reserve the doctor's or patient's slot.

## 4. Business rules

### Slot grid and working hours

1. Appointment start times must align with the clinic-local half-hour grid: minutes must be `00` or `30`, and seconds and microseconds must be zero.
2. Working-hour intervals must use the same grid. Their start and end times must be aligned to `:00` or `:30`, with the end strictly later than the start.
3. An appointment must fit entirely within a single working-hour interval.
4. A slot is not bookable if it falls outside the doctor's working hours or overlaps an existing confirmed appointment.

### Time and booking horizon

5. Appointments cannot be booked in the past.
6. New bookings and rescheduling require at least one hour's notice.
7. Appointments can be booked no more than 60 calendar days ahead, measured using the clinic's local calendar date.
8. The clinic timezone is `Africa/Nairobi`. Availability date queries are interpreted in this timezone, while appointment timestamps are stored and compared as timezone-aware UTC values.
9. The current time used by business rules will be injectable, allowing deterministic tests of notice and booking-horizon boundaries.

### Appointment conflicts and lifecycle

10. A doctor cannot have two confirmed appointments at the same slot.
11. A patient cannot have two confirmed appointments at the same slot, even with different doctors.
12. Booking and availability use the same slot-generation and validation rules.
13. Cancellation requires a reason. The appointment is retained with `CANCELLED` status, freeing the slot.
14. Repeated cancellation is rejected with `409 Conflict`.
15. A cancelled appointment cannot be rescheduled.
16. Rescheduling validates the destination as a fresh booking. If validation or conflict checks fail, the original appointment remains unchanged.
17. Rescheduling to the appointment's existing start time is rejected with `400 Bad Request`.

### Availability edge cases

18. An inactive doctor is not bookable. The availability endpoint returns `404 Not Found` for an inactive doctor.
19. A past date or a date with no working intervals for that weekday returns `200 OK` with an empty list of bookable slots.
20. Availability never exposes patient-identifying information about occupied appointments.
21. Schedule exceptions, such as one-off holidays, are outside the initial scope.



### Working-hour integrity

- Working intervals for the same doctor and weekday must not overlap. Adjacent intervals are allowed.
- Working intervals must have a valid start and end, follow the clinic's `:00`/`:30` grid, and have an end later than the start.
- Working-hour validation must run when creating or updating a schedule, not only when booking an appointment.

### Availability authentication

- Doctor availability requires authentication.
- Authenticated users may retrieve availability without receiving patient-identifying information about occupied appointments.
- Inactive doctors are not bookable, and their availability endpoint returns `404 Not Found`.


### Authentication and authorization

22. Authentication is required for protected appointment operations.
23. Patients may access only their own appointments.
24. Requests for another patient's appointment or appointment history return `404 Not Found` to avoid disclosing resource existence.
25. `403 Forbidden` is used for role or permission restrictions where the resource's existence need not be concealed.


### Role permissions

- **PATIENT:** May view availability, book appointments for themselves, cancel or reschedule their own appointments, and retrieve their own upcoming appointments.
- **DOCTOR:** May view their own appointment information and schedule-related information. They cannot access another doctor's private appointment details or manage another doctor's schedule without explicit permission.
- **STAFF:** May use authorized administrative functions to manage clinic users, doctor profiles, working hours, and appointments.
- Django's `is_staff` and superuser permissions govern Django admin access separately from the application role.
- All protected operations must enforce permissions on the server; hiding UI controls is not sufficient.

### Booking-horizon policy

The 60-day maximum is an explicit initial clinic policy, not a requirement specified in the assessment. It avoids accepting appointments too far into the future. It can be made configurable if clinic requirements change.

## 5. API contract

These are the planned endpoints. Final request schemas, response bodies, and implementation status will be verified against the code and tests before submission.

### Book an appointment

`POST /appointments`

Creates an appointment for an available doctor slot.

The API validates the authenticated patient's identity, requested time, doctor's active status and working hours, slot alignment, booking horizon, minimum notice, and doctor/patient conflicts.

Expected success status: `201 Created`.

### Retrieve doctor availability

`GET /doctors/{id}/availability?date=YYYY-MM-DD`

Returns bookable 30-minute slots for the requested clinic-local date.

The service generates valid working-hour slots, retrieves the doctor's confirmed appointments for the requested date, and excludes occupied or otherwise invalid slots. It will avoid querying the database separately for each candidate slot.

Expected success status: `200 OK`.

A past date or a date without working intervals returns an empty list. An inactive or nonexistent doctor returns `404 Not Found`.

### Cancel an appointment

`PATCH /appointments/{id}/cancel`

Requires a cancellation reason. The appointment is retained with cancelled status, and its slot becomes available.

Repeated cancellation is rejected.

Expected success status: `200 OK`.

### Reschedule an appointment

`PATCH /appointments/{id}/reschedule`

Moves an existing confirmed appointment to a new valid slot. The same booking rules apply, including the minimum notice, 60-day horizon, and doctor/patient conflict checks.

The operation updates the existing appointment inside a transaction. If validation or conflict checks fail, the original appointment time remains unchanged. Rescheduling to the existing time is rejected.

Expected success status: `200 OK`.

### Retrieve a patient's upcoming appointments

`GET /patients/{id}/appointments`

Returns the authenticated patient's confirmed appointments in the future, sorted by start time ascending.

The requested patient ID must match the authenticated user's patient profile.

Expected success status: `200 OK`.

## 6. Validation and HTTP errors

The API will use consistent, meaningful HTTP responses.

- `200 OK`: Successful read or update.
- `201 Created`: Successful appointment creation.
- `400 Bad Request`: Malformed input or business-rule validation failure, including an off-grid time or rescheduling to the same time.
- `401 Unauthorized`: Authentication is missing or invalid.
- `403 Forbidden`: The authenticated user lacks the required role or permission.
- `404 Not Found`: A resource does not exist or is intentionally concealed from the requester.
- `409 Conflict`: A doctor or patient slot conflict, repeated cancellation, or another invalid appointment state transition.

The final implementation will define and test specific error response bodies rather than relying on inconsistent framework defaults.

## 7. Data integrity and concurrency

Application-level validation provides useful errors, but it cannot alone prevent two simultaneous requests from booking the same slot.

The database design will use named conditional unique constraints:

- `uniq_confirmed_doctor_slot`: unique `(doctor, start_time)` for confirmed appointments.
- `uniq_confirmed_patient_slot`: unique `(patient, start_time)` for confirmed appointments.

Cancelled appointments are excluded from both constraints.

These constraints rely on fixed 30-minute duration and aligned start times. Slot-grid validation is therefore a required part of the design, not an optional convenience.

The application will check for conflicts before attempting writes to provide clear errors. The database constraints remain the final safeguard against simultaneous booking attempts.

When PostgreSQL reports an integrity violation, the application will inspect the underlying constraint name and map known violations to meaningful `409 Conflict` responses. Doctor-slot and patient-slot conflicts will have distinct messages. Unrelated integrity errors will not be incorrectly reported as booking conflicts.

Cancellation and rescheduling will use transactions. Appointment rows will be locked during state-changing operations where appropriate, preventing concurrent changes to the same appointment from silently overwriting one another.

If appointment durations become variable, the overlap-prevention strategy will need to be reconsidered. A PostgreSQL exclusion constraint or another interval-overlap approach may then be appropriate.

## 8. Testing strategy

Tests will cover the business rules and API behavior, including:

- Booking a valid slot.
- Rejecting times outside working hours and times in the past.
- Rejecting off-grid start times and invalid working-hour intervals.
- Rejecting slots with less than one hour's notice.
- Enforcing the 60-calendar-day booking horizon.
- Testing exact notice and horizon boundaries using a controlled clock.
- Preventing doctor and patient double-booking.
- Returning accurate availability.
- Returning an empty availability list for past dates and weekdays without working hours.
- Rejecting inactive doctors.
- Cancelling with a reason and freeing the slot.
- Rejecting repeated cancellation.
- Rescheduling successfully and rejecting invalid destinations without changing the original booking.
- Rejecting rescheduling to the same time or of a cancelled appointment.
- Enforcing authentication, roles, and appointment ownership.
- Returning upcoming appointments in chronological order.
- Handling database conflicts and transaction rollback.

Tests will run against PostgreSQL so database-specific constraints are exercised. Transactional tests will be used where appropriate for locking and concurrency-sensitive behavior.

## 9. Local development

### Prerequisites

- Python 3.11
- PostgreSQL
- Git

### Setup

1. Clone the repository.
2. Create and activate a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Copy `config/.env.example` to `config/.env` and configure local values.
5. Create the configured PostgreSQL database and database user.
6. Run migrations.
7. Create a superuser if administrative access is needed.
8. Start the development server.

Example commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Run tests with:

```bash
pytest
```

The environment file must never be committed. `.env.example` documents required variable names without containing real credentials.

## 10. Deployment and CI/CD

**Deployment provider:** To be finalized after verifying current hosting limits, database connectivity, and deployment requirements.

The intended pipeline will:

1. Run automated tests on pull requests.
2. Block merging when required checks fail.
3. Deploy automatically when changes are merged into the designated deployment branch.
4. Run against PostgreSQL rather than substituting SQLite.

Before submission, this section will be updated with the actual public API URL, deployment provider, branch and trigger configuration, and verified pipeline status.

## 11. Design trade-offs and future improvements

- **Fixed appointment duration:** Simplifies slot generation and conflict detection. Variable durations would require stronger interval-overlap protection.
- **Single clinic timezone:** Uses `Africa/Nairobi` for the initial clinic. Multi-region support could introduce configurable clinic or doctor timezones.
- **Recurring working hours:** Support normal weekly schedules and split shifts. One-off holidays and schedule exceptions are deferred.
- **60-day booking horizon:** Provides a reasonable initial policy and can be made configurable.
- **Database uniqueness constraints:** Protect aligned fixed-duration slots. The constraints must be reconsidered if the appointment model changes.
- **Injectable clock:** Makes time-dependent rules deterministic and prevents boundary tests from depending on the actual time of execution.
- **Minimal modular architecture:** Separates accounts, patient profiles, doctor schedules, and appointment behavior without introducing unnecessary services or infrastructure.

## 12. AI-assisted development reflection

This project uses AI tools as development support, not as a substitute for engineering judgment. The final submission will document real examples from the work.

- **Where AI was used:** Record the specific design, implementation, debugging, testing, and deployment tasks where applicable.
- **Helpful suggestion:** Include a real prompt, the suggestion received, and how it improved the design or implementation.
- **Incorrect or incomplete suggestion:** Describe a real example, how it was checked, and what was corrected.
- **Independent decisions:** Explain at least two decisions made or verified independently, with their reasoning and trade-offs.

All examples will reflect the actual development process. Final claims will be checked against the code, test results, and deployment configuration.

## 13. Implementation progress

Update this checklist as development proceeds.

- [ ] **Implemented:** Environment configuration and custom user model.
- [ ] **Implemented:** Patient and doctor profile models.
- [ ] **Implemented:** Working-hour model and grid validation.
- [ ] **Implemented:** Appointment model and named database constraints.
- [ ] **Implemented:** Authentication, permissions, and API endpoints.
- [ ] **Verified:** Booking, availability, cancellation, and rescheduling tests.
- [ ] **Verified:** Patient double-booking and database conflict handling.
- [ ] **Verified:** PostgreSQL test suite.
- [ ] **Verified:** CI pipeline.
- [ ] **Verified:** Public deployment and documented API URL.
- [ ] **Completed:** AI reflection based on actual development work.
