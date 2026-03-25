from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from backend.md_quiz.config import PROJECT_ROOT, load_runtime_defaults
from backend.md_quiz.models import ProcessHeartbeat, RuntimeConfig
from backend.md_quiz.storage import JobStore, ProcessStore, RuntimeConfigStore
from backend.md_quiz.services.support_deps import *

_RUNTIME_JSON_MIGRATION_KEY = "runtime_json_store_migration"


class RuntimeBootstrapError(RuntimeError):
    """Raised when app bootstrap cannot prepare required runtime dependencies."""


def _ensure_exam_paper_for_token(token: str, assignment: dict) -> dict[str, Any] | None:
    """
    Ensure exam_paper exists for a token once candidate identity is available.
    """
    t = str(token or "").strip()
    if not t:
        return None
    try:
        ep = get_exam_paper_by_token(t)
    except Exception:
        ep = None
    if ep:
        return ep

    try:
        candidate_id = int(assignment.get("candidate_id") or 0)
    except Exception:
        candidate_id = 0
    if candidate_id <= 0:
        return None

    c = get_candidate(candidate_id) or {}
    exam_key = str(assignment.get("exam_key") or "").strip()
    try:
        exam_version_id = int(assignment.get("exam_version_id") or 0)
    except Exception:
        exam_version_id = 0
    phone = str(c.get("phone") or "").strip()
    if not exam_key or not phone:
        return None

    a_status = str(assignment.get("status") or "").strip()
    status_map = {
        "invited": "invited",
        "verified": "verified",
        "in_exam": "in_exam",
        "grading": "grading",
        "graded": "finished",
    }
    status = status_map.get(a_status, "invited")

    inv = assignment.get("invite_window") or {}
    if not isinstance(inv, dict):
        inv = {}
    invite_start_date = str(inv.get("start_date") or "").strip() or None
    invite_end_date = str(inv.get("end_date") or "").strip() or None

    try:
        create_exam_paper(
            candidate_id=candidate_id,
            phone=phone,
            exam_key=exam_key,
            exam_version_id=(exam_version_id or None),
            token=t,
            invite_start_date=invite_start_date,
            invite_end_date=invite_end_date,
            status=status,
        )
    except Exception:
        pass
    try:
        return get_exam_paper_by_token(t)
    except Exception:
        return None


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Read runtime json failed: %s", path)
        return {}
    try:
        value = json.loads(text)
    except Exception:
        logger.exception("Parse runtime json failed: %s", path)
        return {}
    return value if isinstance(value, dict) else {}


def _migrate_runtime_json_state() -> None:
    marker = get_runtime_kv(_RUNTIME_JSON_MIGRATION_KEY) or {}
    if bool(marker.get("done")):
        return

    runtime_root = (PROJECT_ROOT / "storage" / "runtime").resolve()
    if not runtime_root.exists():
        set_runtime_kv(
            _RUNTIME_JSON_MIGRATION_KEY,
            {"done": True, "migrated_at": datetime.now(UTC).isoformat(), "reason": "runtime-dir-missing"},
        )
        return

    summary = {"runtime_config": False, "jobs": 0, "processes": 0}
    runtime_defaults = RuntimeConfig(**load_runtime_defaults().__dict__)
    runtime_config_store = RuntimeConfigStore(runtime_defaults)
    job_store = JobStore()
    process_store = ProcessStore()

    config_path = runtime_root / "runtime-config.json"
    config_payload = _read_json_file(config_path)
    if config_payload and not get_runtime_kv("runtime_config"):
        try:
            merged = runtime_defaults.model_dump()
            merged.update(config_payload)
            runtime_config_store.save(RuntimeConfig.model_validate(merged))
            summary["runtime_config"] = True
        except Exception:
            logger.exception("Runtime config json migration failed: %s", config_path)

    jobs_path = runtime_root / "jobs.json"
    jobs_payload = _read_json_file(jobs_path)
    for raw in jobs_payload.get("jobs") or []:
        if not isinstance(raw, dict):
            continue
        try:
            job_store.import_record(raw)
            summary["jobs"] = int(summary["jobs"]) + 1
        except Exception:
            logger.exception("Runtime job json migration failed: %s", raw.get("id"))

    processes_path = runtime_root / "processes.json"
    processes_payload = _read_json_file(processes_path)
    for raw in (processes_payload.get("processes") or {}).values():
        if not isinstance(raw, dict):
            continue
        try:
            heartbeat = ProcessHeartbeat.model_validate(raw)
            process_store.upsert(heartbeat)
            summary["processes"] = int(summary["processes"]) + 1
        except Exception:
            logger.exception("Process heartbeat json migration failed: %s", raw.get("name"))

    set_runtime_kv(
        _RUNTIME_JSON_MIGRATION_KEY,
        {
            "done": True,
            "migrated_at": datetime.now(UTC).isoformat(),
            "summary": summary,
        },
    )


def bootstrap_runtime() -> None:
    try:
        init_db()
    except RuntimeError as e:
        raise RuntimeBootstrapError(str(e)) from e
    try:
        _migrate_runtime_json_state()
    except Exception:
        logger.exception("Runtime json migration failed")
    try:
        migrate_legacy_exam_data()
    except Exception:
        logger.exception("Legacy exam version migration failed")


__all__ = ["RuntimeBootstrapError", "_ensure_exam_paper_for_token", "bootstrap_runtime"]
