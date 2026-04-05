from __future__ import annotations

from typing import Any

from backend.md_quiz.services.exam_repo_sync_repo import _normalize_repo_url
from backend.md_quiz.services.exam_repo_sync_shared import (
    EXAM_REPO_BINDING_KEY,
    EXAM_SYNC_JOB_KIND,
    EXAM_SYNC_STATE_KEY,
    ExamRepoSyncError,
    _utc_now,
)
from backend.md_quiz.storage import JobStore
from backend.md_quiz.storage.db import (
    clear_exam_domain_data_and_set_repo_binding,
    get_runtime_kv,
    set_runtime_kv,
)


def _jobs_store():
    return JobStore()


def _read_git_sync_state() -> dict[str, Any]:
    return get_runtime_kv(EXAM_SYNC_STATE_KEY) or {}


def read_exam_repo_sync_state() -> dict[str, Any]:
    return _read_git_sync_state()


def _read_exam_repo_binding_state() -> dict[str, Any]:
    raw = get_runtime_kv(EXAM_REPO_BINDING_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    repo_url = str(raw.get("repo_url") or "").strip()
    if not repo_url:
        return {}
    return {
        "repo_url": repo_url,
        "bound_at": str(raw.get("bound_at") or "").strip(),
        "updated_at": str(raw.get("updated_at") or "").strip(),
    }


def read_exam_repo_binding() -> dict[str, Any]:
    return _read_exam_repo_binding_state()


def _write_exam_repo_binding(repo_url: str, *, bound_at: str | None = None, updated_at: str | None = None) -> dict[str, Any]:
    normalized_url = _normalize_repo_url(repo_url)
    current = _read_exam_repo_binding_state()
    timestamp = str(updated_at or "").strip() or _utc_now()
    payload = {
        "repo_url": normalized_url,
        "bound_at": str(bound_at or current.get("bound_at") or timestamp).strip() or timestamp,
        "updated_at": timestamp,
    }
    set_runtime_kv(EXAM_REPO_BINDING_KEY, payload)
    return payload


def _fresh_git_sync_state(repo_url: str) -> dict[str, Any]:
    return {
        "repo_url": _normalize_repo_url(repo_url),
        "status": "idle",
        "last_job_id": "",
        "last_error": "",
        "last_result": {},
        "last_commit": "",
        "queued_at": "",
        "started_at": "",
        "finished_at": "",
    }


def _reset_git_sync_state(repo_url: str) -> dict[str, Any]:
    payload = _fresh_git_sync_state(repo_url)
    set_runtime_kv(EXAM_SYNC_STATE_KEY, payload)
    return payload


def _write_git_sync_state(**updates: Any) -> dict[str, Any]:
    current = _read_git_sync_state()
    current.update(updates)
    set_runtime_kv(EXAM_SYNC_STATE_KEY, current)
    return current


def _current_exam_repo_sync_job():
    store = _jobs_store()
    return next(
        (job for job in store.list_jobs() if job.kind == EXAM_SYNC_JOB_KIND and job.status in {"pending", "running"}),
        None,
    )


def _build_sync_enqueue_result(result: dict[str, Any] | None, *, error: str = "") -> dict[str, Any]:
    payload = dict(result or {})
    payload["job_id"] = str(payload.get("job_id") or "").strip()
    payload["status"] = str(payload.get("status") or "").strip()
    payload["error"] = str(error or "").strip()
    payload["created"] = bool(payload.get("created"))
    payload["enqueued"] = bool(payload["job_id"]) or bool(payload["status"]) or bool(payload["created"])
    return payload


def enqueue_exam_repo_sync(repo_url: str | None = None) -> dict[str, Any]:
    store = _jobs_store()
    binding = _read_exam_repo_binding_state()
    bound_repo_url = str(binding.get("repo_url") or "").strip()
    requested_repo_url = str(repo_url or "").strip()
    if requested_repo_url:
        normalized_url = _normalize_repo_url(requested_repo_url)
        if bound_repo_url and bound_repo_url != normalized_url:
            raise ExamRepoSyncError("当前实例已绑定其他仓库，请走重新绑定流程")
    else:
        normalized_url = bound_repo_url
    if not normalized_url:
        raise ExamRepoSyncError("当前实例尚未绑定仓库")
    existing = _current_exam_repo_sync_job()
    if existing is not None:
        _write_git_sync_state(
            repo_url=normalized_url,
            last_job_id=existing.id,
            status=existing.status,
        )
        return {"job_id": existing.id, "created": False, "status": existing.status}
    job = store.enqueue(EXAM_SYNC_JOB_KIND, payload={"repo_url": normalized_url}, source="admin")
    _write_git_sync_state(
        repo_url=normalized_url,
        last_job_id=job.id,
        status="queued",
        queued_at=job.created_at,
        last_error="",
        last_result={},
        started_at="",
        finished_at="",
    )
    return {"job_id": job.id, "created": True, "status": job.status}


def _enqueue_bound_exam_repo_sync_with_fallback() -> dict[str, Any]:
    try:
        return _build_sync_enqueue_result(enqueue_exam_repo_sync())
    except Exception as exc:
        return _build_sync_enqueue_result(None, error=str(exc))


def bind_exam_repo(repo_url: str) -> dict[str, Any]:
    normalized_url = _normalize_repo_url(repo_url)
    current_binding = _read_exam_repo_binding_state()
    if str(current_binding.get("repo_url") or "").strip():
        raise ExamRepoSyncError("当前实例已绑定仓库，请走重新绑定流程")
    if _current_exam_repo_sync_job() is not None:
        raise ExamRepoSyncError("当前已有同步任务在执行，请等待完成后再试")
    now_iso = _utc_now()
    binding = _write_exam_repo_binding(normalized_url, bound_at=now_iso, updated_at=now_iso)
    _reset_git_sync_state(normalized_url)
    return {
        "binding": binding,
        "sync": _enqueue_bound_exam_repo_sync_with_fallback(),
    }


def rebind_exam_repo(repo_url: str) -> dict[str, Any]:
    normalized_url = _normalize_repo_url(repo_url)
    current_binding = _read_exam_repo_binding_state()
    previous_repo_url = str(current_binding.get("repo_url") or "").strip()
    if not previous_repo_url:
        raise ExamRepoSyncError("当前实例尚未绑定仓库")
    if _current_exam_repo_sync_job() is not None:
        raise ExamRepoSyncError("当前已有同步任务在执行，请等待完成后再试")
    now_iso = _utc_now()
    binding = {
        "repo_url": normalized_url,
        "bound_at": now_iso,
        "updated_at": now_iso,
    }
    cleanup = clear_exam_domain_data_and_set_repo_binding(
        binding_key=EXAM_REPO_BINDING_KEY,
        binding_value=binding,
        sync_state_key=EXAM_SYNC_STATE_KEY,
        sync_state_value=_fresh_git_sync_state(normalized_url),
    )
    return {
        "binding": binding,
        "previous_repo_url": previous_repo_url,
        "cleanup": cleanup,
        "sync": _enqueue_bound_exam_repo_sync_with_fallback(),
    }


__all__ = [
    "_write_git_sync_state",
    "bind_exam_repo",
    "enqueue_exam_repo_sync",
    "read_exam_repo_binding",
    "read_exam_repo_sync_state",
    "rebind_exam_repo",
]
