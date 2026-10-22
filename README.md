# Savannah Clinic Appointment API

A REST API for a small clinic (5 doctors, 30-minute slots) where patients view a doctor's free slots for a day, book one, cancel, or reschedule. Built with Python, Django REST Framework and PostgreSQL.

| | |
|---|---|
| **Live API** | https://savannah-clinic-api.onrender.com |
| **Repository** | https://github.com/Jess2001/Savannah-Backend-Dev-Assessment |
| **Deploys from** | `main` (via GitHub Actions, after the tests pass) |
| **API docs (Swagger)** | https://savannah-clinic-api.onrender.com/docs |
| **Postman collection** | [`docs/Savannah-Clinic-API.postman_collection.json`](docs/Savannah-Clinic-API.postman_collection.json) (30 requests, 62 assertions) |

> **First request may be slow.** The API runs on Render's free tier, which sleeps after 15 minutes without traffic and needs about a minute to wake. The Neon database also sleeps when idle, so the first database request after a quiet period can take a few extra seconds. Open `/health` first to wake the service.

## Try it in 60 seconds

Demo accounts (created by `seed_demo`, password for all: `ClinicDemo123!`):

| Username | Role | Can do |
|---|---|---|
| `patient_one`, `patient_two` | PATIENT | book, cancel/reschedule own, list own upcoming |
| `staff_demo` | STAFF | view, cancel and reschedule any appointment (cannot book) |
| `dr_amina`, `dr_brian`, `dr_cynthia`, `dr_david`, `dr_esther` | DOCTOR | availability only (no appointment access yet) |

Doctor ids start at 1. Dr. Amina, Brian and Cynthia work Mon-Fri 08:00-17:00, Dr. David works Mon/Wed/Fri 09:00-15:00, Dr. Esther works Tue-Sat 10:00-18:00 (clinic time).

```bash
# 1. Log in (returns "access" and "refresh" tokens)
curl -X POST https://savannah-clinic-api.onrender.com/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"patient_one","password":"ClinicDemo123!"}'

# 2. See free slots (use any weekday within the next 60 days)
curl "https://savannah-clinic-api.onrender.com/doctors/1/availability?date=2026-10-26" \
  -H "Authorization: Bearer <access>"

# 3. Book one (times are ISO 8601 with a timezone; 06:00Z = 09:00 Nairobi)
curl -X POST https://savannah-clinic-api.onrender.com/appointments \
  -H "Authorization: Bearer <access>" -H "Content-Type: application/json" \
  -d '{"doctor_id":1,"start_time":"2026-10-26T06:00:00Z"}'
```

Or skip curl: open `/docs`, log in via `POST /auth/token`, click **Authorize**, paste the access token, and try every endpoint from the browser. The Postman collection runs the whole flow, including the failure cases.

## Project status

| Area | Status | Evidence |
|---|---|---|
| System design and business rules | Verified | Sections 1-4; each rule has a test |
| Data model and database constraints | Verified | Migrations; constraint tests against PostgreSQL |
| Booking, cancel, reschedule, availability | Verified | `appointments/test_services.py`, `appointments/test_api.py` |
| Concurrency (double booking) | Verified | Two-thread test: exactly one booking wins |
| Auth, roles, ownership | Verified | API tests per role |
| Deployment | Verified | Postman collection passes against the live URL |
| CI/CD | Verified | GitHub Actions: tests on every PR, deploy after merge to `main` |
| API documentation | Verified | Swagger UI at `/docs`, schema at `/schema`; `config/test_docs.py` fails if an endpoint drops out of the schema |

*Implemented* = the code exists. *Verified* = automated tests or deployment checks demonstrate it. Known gaps are listed honestly in section 10.

---

## 1. System design

### The problem

A clinic with 5 doctors needs online booking. Each doctor has set working hours and works in 30-minute slots. A patient must see free slots for a doctor on a given day, pick one and book it. A booked slot must not be available to anyone else. Patients must be able to cancel. "We're starting small but want to grow."

### Components

The code is split into four Django apps, each with one responsibility:

| App | Responsibility |
|---|---|
| `accounts` | Custom `User` model with an application role (`PATIENT`, `DOCTOR`, `STAFF`) |
| `patients` | Patient profile (one-to-one with a user) |
| `doctors` | Doctor profile and weekly working hours |
| `appointments` | Appointment model, availability, booking rules, API |

Inside `appointments`, the layers are deliberately separate:

```
appointments/
  models.py             Appointment + database constraints (what the DB guarantees)
  availability.py       Slot generation and the booking-window rules (pure logic)
  services.py           book / cancel / reschedule: all business rules live here
  exceptions.py         Business-rule errors, each carrying an HTTP status and a code
  serializers.py        Request validation and response shape
  permissions.py        Who may call which endpoint
  views.py / urls.py    Thin HTTP layer: authorise, call a service, return JSON
  exception_handler.py  One consistent JSON error shape for every failure
config/views.py         /health and / (public)
```

**Why services?** The same rules apply to booking and rescheduling, and the HTTP layer should not own them. Services are plain functions that tests call directly, with the current time passed in, so every rule is testable without HTTP and without waiting for real time to pass.

### Data model

- **User**: Django's `AbstractUser` plus `role`. Defined before the first migration, because swapping the user model later is painful. Superusers created from the command line always get role `STAFF`.
- **Patient**: one-to-one with a user (`related_name="patient_profile"`), optional phone number.
- **Doctor**: one-to-one with a user, specialization, `is_active`.
- **DoctorWorkingHour**: doctor, weekday (0 = Monday ... 6 = Sunday, matching Python), start time, end time. **One interval per doctor per weekday**; a weekday without a row is a day off.
- **Appointment**: patient, doctor, `start_time` (UTC), `status` (`CONFIRMED`, `CANCELLED`, `COMPLETED`, `NO_SHOW`), `cancellation_reason`, timestamps. The end time is derived (`start_time + 30 minutes`), not stored.

### Key decisions and trade-offs

1. **Slots are calculated, not stored.** The alternative is a `Slot` table with a row per doctor per 30 minutes, which has to be generated and kept in sync whenever hours change. Computing "working hours minus confirmed appointments" needs no extra rows and cannot drift. Availability makes one query for the doctor's confirmed appointments that day and subtracts in memory (no query per slot).
2. **The database is the final authority on double booking.** An availability check in code cannot stop two simultaneous requests from both passing it. Two partial unique constraints (section 7) make the database reject the second insert; the application then translates that error into a clear `409`.
3. **Fixed 30-minute grid.** Because every appointment is exactly 30 minutes and must start on `:00` or `:30`, two appointments overlap only if they start at the same instant. That makes a plain unique constraint on `(doctor, start_time)` equivalent to "no overlaps". The grid check is therefore a required rule, not a nicety. For variable durations I would switch to a PostgreSQL exclusion constraint on a time range.
4. **Booking and availability share one slot generator.** `validate_slot` checks the requested time against `working_slots`, the same function availability is built from, so a slot cannot be shown as free and then rejected for hours, or the reverse.
5. **Times are stored in UTC; rules use the clinic's timezone (`Africa/Nairobi`).** "08:00-17:00", "a calendar day" and "60 days ahead" only mean something in the clinic's local time. UTC storage keeps timestamps unambiguous. One clinic timezone (not per doctor) avoids daylight-saving complexity Kenya doesn't have; a timezone column is the documented upgrade for multiple regions.
6. **Reschedule updates the same row in a transaction.** If the new slot fails validation or hits a constraint, the transaction rolls back and the original appointment is untouched. The old slot frees itself because the row moved. The alternative (cancel and create a new row) leaves cancelled noise for every reschedule.
7. **Rescheduling is an operation, not a status.** After a reschedule the appointment is still `CONFIRMED`; what changed is when. A history of moves would be an audit log, which is future work.
8. **Locks only where they protect something.** `select_for_update` on the appointment row serialises two simultaneous cancels/reschedules of the *same* appointment. It is deliberately *not* used for booking: a free slot has no row to lock, so the unique constraints do that job and a doctor-level lock would only reduce throughput.
9. **`PROTECT` on appointment foreign keys.** A doctor or patient with appointments cannot be deleted, so history is never silently erased.
10. **Patient identity comes from the token,** never from the request body, so a patient cannot book "as" someone else.

---

## 2. Business rules

**Slot grid and working hours**

1. Appointment start times must be on the clinic-local half-hour grid (minutes `00` or `30`, seconds zero).
2. Each doctor has at most one working interval per weekday. Start and end must be on the grid and end must be later than start (checked in `clean()` and by a database check constraint).
3. An appointment must fit entirely inside the interval (with hours 08:00-17:00 the last slot starts at 16:30).
4. A slot is bookable only if it is within working hours and not taken by a confirmed appointment of that doctor.

**Time**

5. Appointments cannot be booked in the past.
6. Booking and rescheduling need at least one hour's notice (exactly one hour is allowed).
7. Appointments can be booked at most 60 calendar days ahead, measured on the clinic-local date. *(Our own policy; not in the brief.)*
8. The clinic timezone is `Africa/Nairobi`. Availability dates are interpreted in it; timestamps are stored and compared in UTC.
9. The current time is injectable (`now` parameter) in the services and availability code, so notice and horizon boundaries are tested exactly. The HTTP tests use dates relative to the real clock instead.
10. Datetimes in requests must include a timezone; a time without one is rejected with `400` rather than silently assumed to be UTC.

**Conflicts and lifecycle**

11. A doctor cannot have two confirmed appointments in the same slot.
12. A patient cannot have two confirmed appointments in the same slot, even with different doctors.
13. Cancellation requires a non-blank reason. The appointment is kept with status `CANCELLED` and its slot becomes bookable again.
14. Only `CONFIRMED` appointments can be cancelled or rescheduled. Cancelling twice, or touching a cancelled/completed/no-show appointment, returns `409`.
15. Rescheduling validates the destination exactly like a new booking. If it fails, the original is unchanged.
16. Rescheduling to the appointment's current time is rejected with `400`.
17. `COMPLETED` and `NO_SHOW` exist so the lifecycle can record outcomes. They are set by staff in Django admin; there is no API endpoint for them yet.

**Availability**

18. An inactive doctor is not bookable (booking returns `400`) and their availability endpoint returns `404`.
19. A past date, a date beyond the 60-day horizon, or a weekday with no working hours returns `200` with an empty `slots` list.
20. Availability never exposes patient information.
21. Doctor availability requires authentication (any role).
22. Schedule exceptions such as one-off holidays are out of scope.

**Roles and ownership**

| Role | Book | Cancel / reschedule | View appointment list | Availability |
|---|---|---|---|---|
| PATIENT | yes | own only (others return 404) | own only | yes |
| STAFF | no | any | any patient's | yes |
| DOCTOR | no | no (403) | no (403) | yes |

23. A patient asking for another patient's appointment or list gets `404`, not `403`, so the existence of the record is not revealed. `403` is used for role restrictions.
24. `is_staff` (Django admin access) is separate from the application `role`. Managing users, doctors and working hours is done in Django admin by `is_staff` users; the API exposes none of that.

---

## 3. API reference

All endpoints require `Authorization: Bearer <access token>` except `/health`, `/`,`/docs `,`/schema` and the token endpoints. URLs have no trailing slash. All bodies are JSON.

| Method | Endpoint | Who | Success |
|---|---|---|---|
| `POST` | `/auth/token` | anyone | `200` access + refresh tokens (1 h / 1 day) |
| `POST` | `/auth/token/refresh` | anyone | `200` new access token |
| `POST` | `/appointments` | patient | `201` |
| `GET` | `/doctors/{id}/availability?date=YYYY-MM-DD` | any authenticated user | `200` |
| `PATCH` | `/appointments/{id}/cancel` | patient (own), staff | `200` |
| `PATCH` | `/appointments/{id}/reschedule` | patient (own), staff | `200` |
| `GET` | `/patients/{id}/appointments` | patient (own), staff | `200` (bonus) |
| `GET` | `/health`, `/` | anyone | `200` |
| `GET` | `/docs` | anyone | `200` interactive Swagger UI |
| `GET` | `/schema` | anyone | `200` OpenAPI schema (importable into Postman) |


**Book** request: `{"doctor_id": 1, "start_time": "2026-10-26T06:00:00Z"}`.
**Cancel** request: `{"reason": "Feeling better"}`. **Reschedule** request: `{"start_time": "2026-10-26T06:30:00Z"}`.

**Appointment response** (book, cancel, reschedule, and each list item):

```json
{
  "id": 12,
  "doctor_id": 1,
  "doctor_name": "Dr. Amina Hassan",
  "patient_id": 1,
  "start_time": "2026-10-26T06:00:00Z",
  "end_time": "2026-10-26T06:30:00Z",
  "local_start_time": "2026-10-26T09:00:00+03:00",
  "status": "CONFIRMED",
  "cancellation_reason": "",
  "created_at": "2026-10-21T11:02:41.512083Z"
}
```

**Availability response:**

```json
{
  "doctor_id": 1,
  "date": "2026-10-26",
  "timezone": "Africa/Nairobi",
  "slots": [
    {"start_time": "2026-10-26T05:00:00Z", "end_time": "2026-10-26T05:30:00Z", "local_start_time": "2026-10-26T08:00:00+03:00"}
  ]
}
```

`GET /patients/{id}/appointments` returns the patient's confirmed, future appointments, soonest first (a plain list, no pagination).

### Errors

Every error has the same shape:

```json
{"error": {"code": "slot_unavailable", "message": "This slot is already booked."}}
```

Validation errors add `"details"` with per-field messages.

| Status | `code` | When |
|---|---|---|
| 400 | `validation_error` | malformed body, missing field, time without timezone |
| 400 | `booking_rule_violation` | off-grid, outside hours, past, under 1 hour notice, beyond 60 days, inactive doctor, same-time reschedule, blank reason |
| 401 | `not_authenticated` | missing or invalid token |
| 403 | `permission_denied` | role not allowed (e.g. staff booking, doctor cancelling) |
| 404 | `not_found` | unknown doctor, or an appointment/list that is not yours |
| 409 | `slot_unavailable` | doctor's slot taken, or you already have an appointment then |
| 409 | `invalid_state` | cancelling twice, rescheduling a cancelled/completed appointment |

---

## 4. Data integrity and concurrency

Named database constraints:

| Constraint | Rule |
|---|---|
| `uniq_confirmed_doctor_slot` | unique `(doctor, start_time)` where status is `CONFIRMED` |
| `uniq_confirmed_patient_slot` | unique `(patient, start_time)` where status is `CONFIRMED` |
| `cancelled_requires_reason` | a `CANCELLED` row must have a non-empty reason |
| `uniq_doctor_weekday_working_hours` | one working interval per doctor per weekday |
| `working_hours_end_after_start` | interval end later than start |

Cancelled rows are excluded from the slot constraints, so a cancelled slot can be rebooked while the cancelled row stays as history.

**How a race is handled.** The service first checks for conflicts to give friendly messages. If two requests pass that check at the same instant, PostgreSQL rejects the second insert. The service reads the *name* of the violated constraint from the database error and returns the matching message (doctor slot vs patient slot). An integrity error from any other constraint is re-raised, never disguised as a booking conflict.

**Limitation (deliberate and documented):** the `:00/:30` grid is enforced by the service layer (and by `clean()` for working hours), not by a database constraint. Anything that bypasses the service, such as Django admin or raw SQL, could create an off-grid appointment. The API is the supported entry point.

---

## 5. Testing

```bash
pytest
```

Roughly 70 automated tests, run against a real PostgreSQL database (so constraints are genuinely exercised):
Swagger UI and schema are public and list every endpoint
| File | Covers |
|---|---|
| `appointments/test_services.py` | availability (18 slots for 08:00-17:00, booked slot hidden, day off, past date, notice window); booking (valid, off-grid 08:15 after 08:00, outside hours, last slot, past, 1-hour boundary, 60-day boundary, doctor and patient double booking, inactive doctor); cancel, reschedule and their failure cases; **a two-thread race proving exactly one booking wins**; a simulated database conflict translated to a clean error |
| `appointments/tests.py` | the database constraints themselves |
| `appointments/test_api.py` | every endpoint over HTTP: status codes, error codes, roles, ownership (404), JWT login flow |
| `doctors/tests.py`, `patients/tests.py`, `accounts/tests.py` | working-hour validation, role/profile consistency, superuser role |
| `appointments/test_seed.py`, `config/test_health.py`,`config/test_docs.py` | idempotent seeding, public health/root endpoints |


The Postman collection in `docs/` (62 assertions) tests the deployed API end to end, including the negative cases, and passes against the live URL.

---

## 6. Local development

Prerequisites: Python 3.11, PostgreSQL, Git.

```bash
git clone https://github.com/Jess2001/Savannah-Backend-Dev-Assessment.git
cd Savannah-Backend-Dev-Assessment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit the values
```

Create a local database and user, for example:

```bash
psql -c "CREATE USER clinic_user WITH PASSWORD 'choose-a-password' CREATEDB;"
psql -c "CREATE DATABASE clinic OWNER clinic_user;"
```

(`CREATEDB` lets pytest create its temporary test database.)

Environment variables (`.env` in the project root, never committed):

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | required |
| `DJANGO_DEBUG` | `True` locally (needed for admin CSS under `runserver`) |
| `DJANGO_ALLOWED_HOSTS` | e.g. `localhost,127.0.0.1` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | local database |
| `DATABASE_URL` | optional; when set it replaces the `DB_*` values (used in production) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | production only |

```bash
python manage.py migrate
python manage.py seed_demo          # demo doctors, patients, staff (safe to re-run)
python manage.py createsuperuser    # your own admin login
python manage.py runserver
pytest
```
With the server running, interactive docs are at http://127.0.0.1:8000/docs.
---

## 7. Deployment and CI/CD

- **Hosting:** Render (web service, free tier) with Neon (serverless PostgreSQL, free plan). Render's own free database expires after a fixed period, which is why the database is on Neon instead.
- **Public URL:** https://savannah-clinic-api.onrender.com
- **Branch that triggers deployment:** `main`.

**Pipeline** (`.github/workflows/ci.yml`):

1. **On every pull request to `main`:** start a PostgreSQL 16 service container, install dependencies, run `makemigrations --check` (fails if a model change has no migration), then run the full test suite.
2. **On every push to `main`** (that is, a merged PR): run the same `test` job, and **only if it passes** run `deploy`, which calls a Render deploy hook (the URL is a GitHub Actions secret). Render's own auto-deploy is switched off, so this pipeline is the only way code ships.
3. Render then runs `build.sh`: install dependencies, `collectstatic`, `migrate`, `seed_demo`, and create the admin account from environment variables.

`main` is protected: changes must come through a pull request and the `test` check must pass before merging.

Start command: `gunicorn config.wsgi:application`. Static files (the Django admin's CSS) are served by WhiteNoise. `/health` is the host's health check; it deliberately never queries the database, so health checks cannot keep the scale-to-zero database awake.

*Trade-off:* the deploy hook only *starts* a Render build; the pipeline does not wait for it to finish. Polling Render's API for the deploy result would close that gap.

---

## 8. Assumptions where the brief was ambiguous

| Question | Decision |
|---|---|
| Who may book? | Authenticated patients, for themselves only. Staff cannot book on a patient's behalf (it would need a "which patient" field). |
| How do doctors have "set working hours"? | A weekly schedule: one interval per weekday, day off = no row. Split shifts deferred. |
| Which timezone? | `Africa/Nairobi` for rules, UTC for storage. |
| Booking horizon? | 1 hour minimum notice (the brief's bonus) and 60 days maximum (our own policy, configurable in one constants file). |
| Can a patient hold two appointments at once? | No, not even with different doctors. |
| What does a cancelled slot do? | Becomes bookable again; the row remains as history. |
| What can be cancelled or rescheduled? | Only `CONFIRMED` appointments. |
| Does availability need a login? | Yes, for consistency (any role). |
| Time without a timezone? | Rejected, not guessed. |

---

## 9. Design trade-offs and future improvements

Deliberately left out, with the upgrade path:

- **Split shifts and holidays:** remove the one-interval-per-weekday constraint and add an overlap check; add a schedule-exceptions model.
- **Variable appointment durations:** replace the unique constraints with a PostgreSQL exclusion constraint over a time range.
- **Multiple timezones / clinics:** add a timezone field on clinic or doctor.
- **Doctor features:** the `DOCTOR` role exists but has no appointment access yet; link doctors to their own appointments and schedule.
- **API for `COMPLETED` / `NO_SHOW`:** staff set these in Django admin today.
- **Staff booking for patients, user registration, token revocation/logout, pagination, rate limiting:** not built; the seed command and demo accounts stand in for registration.
- **Database-level grid enforcement:** currently service-level only (section 4).
- **Deploy verification in CI:** poll the Render deploy to confirm success.
- **Free-tier hosting:** cold starts on the first request after idle time.

---

## 10. AI reflection (Section 4)

**How I worked.** I used AI as a working tool throughout. Claude AI was used to challenge my design decisions and  drafted most of the implementation in small batches, each with an explanation of what it does and why. My role was to direct and verify it: I set the scope, questioned design choices, changed or rejected suggestions, ran every batch myself (tests, migrations, the Postman collection, the deployment), brought back the failures I hit, and debugged my environment and the deployment. I treated every suggestion as a proposal until it ran green.
**1. What did I use AI for across the four sections?**

- **Section 1 — System design and README

I used AI to help reason through the data model, API boundaries, business rules, validation, and edge cases before implementation. You discussed trade-offs and refined the design rather than immediately jumping into coding.

Examples included  UTC storage versus the clinic's Nairobi timezone, working-hour validation, double-booking prevention, and what should happen during cancellation or rescheduling.

- **Section 2 — API implementation and testing

I used AI for implementation guidance, Django configuration, reviewing model and business-rule decisions, and writing targeted tests. You also used it to identify checks to run and interpret the results.

- **Deployment and CI/CD:** Setting up the GitHub Actions workflow and step-by-step Render/Neon setup. Claude checked the current free-tier limits of both hosts before I committed to them. I created the accounts, set the secrets and fixed the problems that came up (a missing `build.sh` on the deploy branch, environment file location, admin login).
- **Testing and documentation:** the Swagger/OpenAPI annotations,the Postman collection, commit structuring, and drafting this README, which I checked against the code.

**2. One example where an AI suggestion improved my work.**

*Prompt:* "I've structured the system design. Evaluate it and challenge my decisions with better options for this assessment, prioritising correctness, complexity cost and growth path."

*Suggestion:* my draft used a PostgreSQL exclusion constraint on `start_time + 30 minutes`. The review pointed out that, because every appointment is exactly 30 minutes and must sit on the half-hour grid, two appointments overlap only if they share a start time, so a partial unique constraint gives the same guarantee, works natively in Django, and is easier to explain. It also warned that an expression on `timestamptz + interval` may not be usable in an index because it is not immutable, and that the grid check must then become an explicit rule. I did not test the exclusion-constraint version, so I treat that warning as the reviewer's flag, not a result I reproduced.

*Effect:* the design became simpler and the grid rule explicit (rule 1), with a test for exactly the dangerous case: 08:00 booked, 08:15 attempted, rejected before it reaches the database.

**3. One example where AI output was wrong, and how I caught it.**

The generated Postman collection's login tests referenced a variable before declaring it. Running the collection showed four failures with `Cannot access 'body' before initialization`, even though every one of those requests returned `200`. That told me the API was fine and the *test script* was broken: the check line ran before the line that defined `body`. I corrected the script order and re-ran the collection to confirm it was clean.


**4. Two decisions I made without AI, and why I trusted my own judgment.**

1. **Rescheduling is an operation, not a status, and the lifecycle also needs `COMPLETED` and `NO_SHOW`.** I distinguished what an appointment currently *is* from an action performed on it: a rescheduled appointment is still `CONFIRMED`, it just moved. And a clinic needs to record whether a visit happened or the patient did not turn up. I trusted my judgment because this is domain modelling about how a clinic works, not a technical detail where I would defer to a tool.
2. **Using database constraints to protect booking correctness
Application-level validation can check whether a slot is available, but two concurrent requests can both pass that check before either saves its appointment. I opted combining validation with database-level uniqueness constraints and transactional handling, rather than relying on an availability check alone.


**How I used AI .** I used AI as a development assistant and a way to challenge my reasoning. It helped me explore design alternatives, understand trade-offs, work through implementation details, identify edge cases, and develop tests and documentation. I treated its suggestions as proposals rather than automatically accepting them. I reviewed suggestions against the assessment requirements, considered their implications, and used testing and debugging to check the resulting behavior. The process helped me move faster while also improving my understanding of the decisions and trade-offs involved.

AI was useful for generating possibilities and explaining unfamiliar details, but it was not a substitute for understanding the system. 
