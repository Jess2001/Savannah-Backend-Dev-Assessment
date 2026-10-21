from rest_framework.test import APIClient


def test_health_is_public_and_needs_no_database():
    response = APIClient().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_lists_the_endpoints():
    response = APIClient().get("/")
    assert response.status_code == 200
    assert "endpoints" in response.json()
