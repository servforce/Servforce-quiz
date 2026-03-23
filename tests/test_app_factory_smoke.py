from __future__ import annotations

from contextlib import nullcontext

import pytest

import web.app_factory as app_factory
import web.routes.admin_shell as admin_shell
import web.routes.public_verify as public_verify
from web.app_factory import create_app
from web.runtime_setup import RuntimeBootstrapError


def _build_smoke_app(monkeypatch):
    monkeypatch.setattr(app_factory, "bootstrap_runtime", lambda app: None)
    monkeypatch.setattr(admin_shell, "_list_exams", lambda: [])
    monkeypatch.setattr(admin_shell, "_peek_cached_system_status_summary", lambda: {})
    monkeypatch.setattr(public_verify, "assignment_locked", lambda token: nullcontext())
    monkeypatch.setattr(
        public_verify,
        "load_assignment",
        lambda token: {
            "token": token,
            "status": "invited",
            "verify": {},
            "sms_verify": {},
            "verify_max_attempts": 3,
        },
    )
    monkeypatch.setattr(public_verify, "_finalize_if_time_up", lambda token, assignment: False)
    monkeypatch.setattr(public_verify, "_ensure_exam_paper_for_token", lambda token, assignment: None)
    return create_app()


def test_create_app_registers_core_routes(monkeypatch):
    app = _build_smoke_app(monkeypatch)

    assert app.template_folder.endswith("/templates")
    assert app.static_folder.endswith("/static")

    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/admin/login" in rules
    assert "/t/<token>" in rules
    assert "/exam/<token>" in rules
    assert "/a/<token>" in rules


def test_create_app_surfaces_bootstrap_errors(monkeypatch):
    def _boom(app):
        raise RuntimeBootstrapError("db down")

    monkeypatch.setattr(app_factory, "bootstrap_runtime", _boom)

    with pytest.raises(RuntimeBootstrapError, match="db down"):
        create_app()


def test_admin_routes_smoke(monkeypatch):
    app = _build_smoke_app(monkeypatch)
    client = app.test_client()

    login_response = client.get("/admin/login")
    assert login_response.status_code == 200

    with client.session_transaction() as session:
        session["admin_logged_in"] = True

    exams_response = client.get("/admin/exams")
    assert exams_response.status_code == 200


def test_public_verify_route_smoke(monkeypatch):
    app = _build_smoke_app(monkeypatch)
    client = app.test_client()

    response = client.get("/t/demo-token")

    assert response.status_code == 200
