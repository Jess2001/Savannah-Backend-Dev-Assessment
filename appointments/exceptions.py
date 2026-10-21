class BookingError(Exception):
    """Base class for every business-rule failure.

    `status_code` is the HTTP status the API returns; `code` is a stable,
    machine-readable label clients can switch on.
    """

    status_code = 400
    code = "booking_error"

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class BookingValidationError(BookingError):
    """The request breaks a rule (off-grid time, outside hours, in the past...)."""

    status_code = 400
    code = "booking_rule_violation"


class SlotUnavailableError(BookingError):
    """The slot is already taken by this doctor or this patient."""

    status_code = 409
    code = "slot_unavailable"


class InvalidStateError(BookingError):
    """The appointment's current status doesn't allow this action."""

    status_code = 409
    code = "invalid_state"
