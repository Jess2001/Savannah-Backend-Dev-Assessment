from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import BookingError

HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    415: "unsupported_media_type",
    429: "throttled",
}

# Headers DRF sets that clients rely on (e.g. WWW-Authenticate on a 401).
PASS_THROUGH_HEADERS = ("WWW-Authenticate", "Retry-After", "Allow")


def _error_response(code, message, status_code, details=None):
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return Response({"error": error}, status=status_code)


def api_exception_handler(exc, context):
    """Every error the API returns has this shape:

    {"error": {"code": "...", "message": "...", "details": {...optional}}}
    """
    if isinstance(exc, BookingError):
        return _error_response(exc.code, exc.message, exc.status_code)

    if isinstance(exc, (Http404, ObjectDoesNotExist)):
        return _error_response("not_found", "Resource not found.", 404)

    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # not an error we recognise: let Django return a 500

    if isinstance(exc, ValidationError):
        new_response = _error_response(
            "validation_error",
            "The request data is invalid.",
            response.status_code,
            details=response.data,
        )
    else:
        data = response.data
        message = (
            data.get("detail", "Request failed.")
            if isinstance(data, dict)
            else "Request failed."
        )
        new_response = _error_response(
            HTTP_ERROR_CODES.get(response.status_code, "error"),
            str(message),
            response.status_code,
        )

    for header in PASS_THROUGH_HEADERS:
        if header in response:
            new_response[header] = response[header]
    return new_response
