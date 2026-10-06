"""HTTP boundary regression: a manager route must never become anonymously readable."""

from fastapi.testclient import TestClient

from app.main import app


def test_manager_routes_reject_anonymous_requests():
    client = TestClient(app)
    for path in ("/api/manager/publications", "/api/manager/jobs", "/api/manager/audit"):
        response = client.get(path)
        assert response.status_code == 401, (path, response.text)
