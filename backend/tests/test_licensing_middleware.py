from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.licensing.state import set_license_state
from app.core.licensing.validator import LicenseState, LicenseStatus
from app.main import license_enforcement_middleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(license_enforcement_middleware)

    @app.post("/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/users")
    async def list_users():
        return {"ok": True}

    @app.post("/timesheets")
    async def create_timesheet():
        return {"ok": True}

    return app


def test_middleware_passes_through_in_saas_mode(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "saas")
    app = _build_test_app()

    with TestClient(app) as client:
        response = client.get("/users")

    assert response.status_code == 200


def test_middleware_blocks_non_auth_when_license_missing(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "self_hosted")
    set_license_state(LicenseState(status=LicenseStatus.MISSING, message="missing"))
    app = _build_test_app()

    with TestClient(app) as client:
        blocked = client.get("/users")
        allowed = client.post("/auth/login")

    assert blocked.status_code == 503
    assert allowed.status_code == 200


def test_middleware_allows_gets_in_read_only_mode(monkeypatch):
    async def _read_only():
        return "read_only"

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "self_hosted")
    monkeypatch.setattr("app.core.licensing.state.get_license_expiry_behavior", _read_only)
    set_license_state(LicenseState(status=LicenseStatus.EXPIRED, message="expired"))
    app = _build_test_app()

    with TestClient(app) as client:
        get_response = client.get("/users")
        post_response = client.post("/timesheets")

    assert get_response.status_code == 200
    assert post_response.status_code == 503


def test_middleware_blocks_all_in_full_lockout_mode(monkeypatch):
    async def _full_lockout():
        return "full_lockout"

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "self_hosted")
    monkeypatch.setattr("app.core.licensing.state.get_license_expiry_behavior", _full_lockout)
    set_license_state(LicenseState(status=LicenseStatus.EXPIRED, message="expired"))
    app = _build_test_app()

    with TestClient(app) as client:
        blocked = client.get("/users")
        auth_allowed = client.post("/auth/login")

    assert blocked.status_code == 503
    assert auth_allowed.status_code == 200


def test_middleware_passes_through_in_grace_mode(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "self_hosted")
    set_license_state(LicenseState(status=LicenseStatus.GRACE, message="grace"))
    app = _build_test_app()

    with TestClient(app) as client:
        response = client.get("/users")

    assert response.status_code == 200
