import re

from rest_framework.test import APIClient


def test_swagger_ui_is_public():
    assert APIClient().get("/docs").status_code == 200


def test_schema_documents_every_endpoint():
    response = APIClient().get("/schema", {"format": "json"})
    assert response.status_code == 200

    # Path parameters may be named {id} or {pk}; treat them the same.
    documented = {
        re.sub(r"\{[^}]+\}", "{id}", path) for path in response.json()["paths"]
    }
    expected = {
        "/appointments",
        "/appointments/{id}/cancel",
        "/appointments/{id}/reschedule",
        "/doctors/{id}/availability",
        "/patients/{id}/appointments",
        "/auth/token",
        "/auth/token/refresh",
    }
    assert expected <= documented
