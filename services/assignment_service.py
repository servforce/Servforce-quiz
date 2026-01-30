from __future__ import annotations

from contextlib import contextmanager
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from config import STORAGE_DIR
from storage.json_store import read_json, write_json

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(token: str) -> threading.Lock:
    t = str(token or "")
    with _LOCKS_GUARD:
        lock = _LOCKS.get(t)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[t] = lock
        return lock


@contextmanager
def assignment_locked(token: str):
    lock = _lock_for(token)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def compute_min_submit_seconds(time_limit_seconds: int, min_submit_seconds: int | None = None) -> int:
    try:
        limit = int(time_limit_seconds or 0)
    except Exception:
        limit = 0
    if limit <= 0:
        return 0
    # half_or_more = (limit + 1) // 2
    half_or_more = 60
    if min_submit_seconds is None:
        return half_or_more
    try:
        given = int(min_submit_seconds or 0)
    except Exception:
        given = 0
    return max(0, max(given, half_or_more))


def create_assignment(
    exam_key: str,
    candidate_id: int,
    base_url: str,
    time_limit_seconds: int = 7200,
    min_submit_seconds: int | None = None,
    verify_max_attempts: int = 3,
    pass_threshold: int = 70,
) -> dict[str, Any]:
    try:
        import qrcode  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency: qrcode. Please install requirements.txt") from e

    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    min_submit_seconds = compute_min_submit_seconds(time_limit_seconds, min_submit_seconds)
    assignment = {
        "token": token,
        "exam_key": exam_key,
        "candidate_id": candidate_id,
        "created_at": now,
        "time_limit_seconds": int(time_limit_seconds),
        "min_submit_seconds": int(min_submit_seconds),
        "verify_max_attempts": int(verify_max_attempts),
        "pass_threshold": int(pass_threshold),
        "verify": {"attempts": 0, "locked": False},
        "timing": {"start_at": None, "end_at": None},
        "answers": {},
        "grading": None,
    }
    write_json(STORAGE_DIR / "assignments" / f"{token}.json", assignment)

    url = f"{base_url.rstrip('/')}/t/{token}"
    img = qrcode.make(url)
    qr_path = STORAGE_DIR / "qr" / f"{token}.png"
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    # Pillow versions may not accept PathLike; ensure str path for compatibility.
    img.save(str(qr_path))

    return {"token": token, "url": url, "qr_path": str(qr_path)}


def load_assignment(token: str) -> dict[str, Any]:
    return read_json(STORAGE_DIR / "assignments" / f"{token}.json")


def save_assignment(token: str, assignment: dict[str, Any]) -> None:
    write_json(STORAGE_DIR / "assignments" / f"{token}.json", assignment)
