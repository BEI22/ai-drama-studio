"""Unified response envelope, request_id propagation and error handling.

PRD sections 23, 28 and 31.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import ForbiddenError, NotFoundError
from app.main import _register_exception_handlers

ENVELOPE_KEYS = {"success", "data", "error", "request_id"}


def test_success_envelope_shape(client: TestClient) -> None:
    body = client.get("/api/v1/health/detail").json()
    assert set(body) >= ENVELOPE_KEYS
    assert body["success"] is True
    assert body["error"] is None


def test_request_id_is_generated_and_echoed_in_header(client: TestClient) -> None:
    response = client.get("/health")
    request_id = response.headers["X-Request-ID"]
    assert request_id.startswith("req_")

    other = client.get("/api/v1/health/detail")
    assert other.json()["request_id"] == other.headers["X-Request-ID"]


def test_incoming_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/api/v1/health/detail", headers={"X-Request-ID": "req_caller_supplied"})
    assert response.headers["X-Request-ID"] == "req_caller_supplied"
    assert response.json()["request_id"] == "req_caller_supplied"


def test_404_returns_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404

    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["request_id"]


def test_405_returns_error_envelope(client: TestClient) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


# --------------------------------------------------------------------------- #
# Handlers exercised against a throwaway app that reuses production wiring.
# --------------------------------------------------------------------------- #
class _Payload(BaseModel):
    name: str


def _handler_app() -> FastAPI:
    app = FastAPI()
    _register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise NotFoundError("Project not found")

    @app.get("/forbidden")
    def forbidden() -> None:
        raise ForbiddenError()

    @app.post("/echo")
    def echo(payload: _Payload) -> dict:
        return {"name": payload.name}

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("secret squashed")

    return app


def test_app_error_handler_maps_code_and_status() -> None:
    with TestClient(_handler_app(), raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "Project not found"
        assert body["success"] is False

        forbidden = test_client.get("/forbidden")
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "FORBIDDEN"


def test_validation_error_handler_returns_details() -> None:
    with TestClient(_handler_app()) as test_client:
        response = test_client.post("/echo", json={})
        assert response.status_code == 422

        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert body["error"]["details"]
        assert body["data"] is None


def test_unhandled_exception_returns_500_without_leaking_details() -> None:
    with TestClient(_handler_app(), raise_server_exceptions=False) as test_client:
        response = test_client.get("/crash")
        assert response.status_code == 500

        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert body["error"]["message"] == "Internal server error"
        assert "secret squashed" not in response.text
