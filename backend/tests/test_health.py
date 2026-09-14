"""Health endpoint contracts (PRD section 31)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_health_matches_prd_contract(client: TestClient) -> None:
    """PRD section 31: ``GET /health`` returns exactly ``{"status": "ok"}``."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_health_is_enveloped(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok"}


def test_health_detail_reports_components(client: TestClient) -> None:
    response = client.get("/api/v1/health/detail")
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["request_id"]
    assert body["request_id"].startswith("req_")

    data = body["data"]
    assert data["status"] in {"ok", "degraded"}
    assert data["version"]
    assert data["environment"] == "test"

    components = {component["name"]: component for component in data["components"]}
    assert components["database"]["status"] == "up"
    # Redis may legitimately be down in developer environments.
    assert components["redis"]["status"] in {"up", "down", "unknown"}


def test_root_metadata_endpoint(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["api"] == "/api/v1"


def test_openapi_is_generated(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert "/api/v1/health/detail" in schema["paths"]
