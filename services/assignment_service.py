from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import hmac
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from config import SECRET_KEY, STORAGE_DIR
from storage.json_store import read_json, write_json

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


_ASSIGNMENT_TOKEN_LEN = 11  # < 12, URL-safe (base64url, no padding)


def _assignment_token_secret() -> bytes:
    # Allow override for rotations; default to app SECRET_KEY.
    raw = (os.getenv("ASSIGNMENT_TOKEN_SECRET") or "").strip()
    if not raw:
        raw = str(SECRET_KEY or "")
    return raw.encode("utf-8", errors="ignore")


def generate_assignment_token(*, exam_key: str, candidate_id: int, phone: str | None = None) -> str:
    """
    Generate a short, URL-safe token (<12 chars) for (candidate, exam) invitations.

    Token space: base64url(HMAC-SHA256(secret, seed)) truncated to `_ASSIGNMENT_TOKEN_LEN`.
    Seed uses real related info + high-resolution time to avoid collisions across multiple invites.
    """
    ek = str(exam_key or "").strip()
    cid = int(candidate_id)
    ph = str(phone or "").strip()
    seed = f"{ek}\n{cid}\n{ph}\n{time.time_ns()}"
    digest = hmac.new(_assignment_token_secret(), seed.encode("utf-8", errors="ignore"), hashlib.sha256).digest()
    b64 = base64.urlsafe_b64encode(digest).decode("ascii", errors="ignore").rstrip("=")
    t = b64[:_ASSIGNMENT_TOKEN_LEN]
    # Defensive fallback; practically never triggers.
    return t or "t" + b64[: max(0, _ASSIGNMENT_TOKEN_LEN - 1)]


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
    # (limit + 1) // 2
    half_or_more = 60
    if min_submit_seconds is None:
        return int(half_or_more)
    try:
        given = int(min_submit_seconds or 0)
    except Exception:
        given = 0
    if given <= 0:
        return 0
    return max(0, max(int(given), int(half_or_more)))


def create_assignment(
    exam_key: str,
    candidate_id: int,
    base_url: str,
    phone: str | None = None,
    invite_start_date: str | None = None,
    invite_end_date: str | None = None,
    time_limit_seconds: int = 7200,
    min_submit_seconds: int | None = None,
    verify_max_attempts: int = 3,
    pass_threshold: int = 70,
) -> dict[str, Any]:
    try:
        import qrcode  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency: qrcode. Please install requirements.txt") from e

    now = datetime.now(timezone.utc).isoformat()
    min_submit_seconds = compute_min_submit_seconds(time_limit_seconds, min_submit_seconds)

    # Ensure we don't overwrite an existing assignment/QR due to token collision.
    for _ in range(50):
        token = generate_assignment_token(exam_key=exam_key, candidate_id=candidate_id, phone=phone)
        assignment_path = STORAGE_DIR / "assignments" / f"{token}.json"
        qr_path = STORAGE_DIR / "qr" / f"{token}.png"
        if assignment_path.exists() or qr_path.exists():
            continue

        assignment = {
            "token": token,
            "exam_key": exam_key,
            "candidate_id": candidate_id,
            "created_at": now,
            "status": "invited",  # invited -> verified -> in_exam -> grading -> graded
            "status_updated_at": now,
            "invite_window": {
                "start_date": (str(invite_start_date or "").strip() or None),
                "end_date": (str(invite_end_date or "").strip() or None),
            },
            "time_limit_seconds": int(time_limit_seconds),
            "min_submit_seconds": int(min_submit_seconds),
            "verify_max_attempts": int(verify_max_attempts),
            "pass_threshold": int(pass_threshold),
            "verify": {"attempts": 0, "locked": False},
            "timing": {"start_at": None, "end_at": None},
            "answers": {},
            "grading_started_at": None,
            "graded_at": None,
            "grading_error": None,
            "grading": None,
        }
        write_json(assignment_path, assignment)

        url = f"{base_url.rstrip('/')}/t/{token}"
        img = qrcode.make(url)
        qr_path.parent.mkdir(parents=True, exist_ok=True)
        # Pillow versions may not accept PathLike; ensure str path for compatibility.
        img.save(str(qr_path))

        return {"token": token, "url": url, "qr_path": str(qr_path)}

    raise RuntimeError("Failed to allocate a unique assignment token after retries")


def load_assignment(token: str) -> dict[str, Any]:
    return read_json(STORAGE_DIR / "assignments" / f"{token}.json")


def save_assignment(token: str, assignment: dict[str, Any]) -> None:
    write_json(STORAGE_DIR / "assignments" / f"{token}.json", assignment)
