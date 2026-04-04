from __future__ import annotations

import pytest

import backend.md_quiz.services.assignment_service as assignment_service


def test_create_assignment_persists_via_db(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        assignment_service,
        "generate_assignment_token",
        lambda **kwargs: "demo-token",
    )

    def _create_assignment_record(token: str, assignment: dict) -> bool:
        recorded["token"] = token
        recorded["assignment"] = assignment
        return True

    monkeypatch.setattr(assignment_service, "create_assignment_record", _create_assignment_record)

    result = assignment_service.create_assignment(
        quiz_key="python-basic",
        candidate_id=12,
        quiz_version_id=7,
        base_url="http://127.0.0.1:5000",
        phone="13800138000",
    )

    assert result == {
        "token": "demo-token",
        "url": "http://127.0.0.1:5000/t/demo-token",
    }
    assert recorded["token"] == "demo-token"
    assert isinstance(recorded["assignment"], dict)
    assert recorded["assignment"]["quiz_key"] == "python-basic"
    assert recorded["assignment"]["quiz_version_id"] == 7
    assert recorded["assignment"]["candidate_id"] == 12
    assert recorded["assignment"]["ignore_timing"] is False


def test_create_assignment_ignore_timing_forces_unlimited_fields(monkeypatch):
    recorded: dict[str, object] = {}

    monkeypatch.setattr(
        assignment_service,
        "generate_assignment_token",
        lambda **kwargs: "demo-token",
    )

    def _create_assignment_record(token: str, assignment: dict) -> bool:
        recorded["token"] = token
        recorded["assignment"] = assignment
        return True

    monkeypatch.setattr(assignment_service, "create_assignment_record", _create_assignment_record)

    assignment_service.create_assignment(
        quiz_key="python-basic",
        candidate_id=12,
        quiz_version_id=7,
        base_url="http://127.0.0.1:5000",
        phone="13800138000",
        time_limit_seconds=300,
        min_submit_seconds=120,
        ignore_timing=True,
    )

    assert isinstance(recorded["assignment"], dict)
    assert recorded["assignment"]["ignore_timing"] is True
    assert recorded["assignment"]["time_limit_seconds"] == 0
    assert recorded["assignment"]["min_submit_seconds"] == 0


def test_load_assignment_reads_from_db(monkeypatch):
    monkeypatch.setattr(
        assignment_service,
        "get_assignment_record",
        lambda token: {"token": token, "quiz_key": "demo", "status": "invited"},
    )

    assignment = assignment_service.load_assignment("demo-token")

    assert assignment["token"] == "demo-token"
    assert assignment["quiz_key"] == "demo"


def test_load_assignment_raises_for_missing_token(monkeypatch):
    monkeypatch.setattr(assignment_service, "get_assignment_record", lambda token: None)

    with pytest.raises(FileNotFoundError):
        assignment_service.load_assignment("missing-token")


def test_save_assignment_writes_to_db(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def _save_assignment_record(token: str, assignment: dict) -> None:
        calls.append((token, assignment))

    monkeypatch.setattr(assignment_service, "save_assignment_record", _save_assignment_record)

    assignment_service.save_assignment("demo-token", {"token": "demo-token", "quiz_key": "demo"})

    assert calls == [("demo-token", {"token": "demo-token", "quiz_key": "demo"})]
