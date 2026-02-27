from __future__ import annotations

from contextlib import contextmanager
import contextvars
from typing import Any, Iterator


_AUDIT_CTX: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("audit_ctx", default={})


@contextmanager
def audit_context(**kwargs: Any) -> Iterator[None]:
    prev = _AUDIT_CTX.get() or {}
    nxt = dict(prev)
    for k, v in dict(kwargs or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if k == "meta" and isinstance(nxt.get("meta"), dict) and isinstance(v, dict):
            merged = dict(nxt.get("meta") or {})
            merged.update(v)
            nxt["meta"] = merged
            continue
        nxt[k] = v
    token = _AUDIT_CTX.set(nxt)
    try:
        yield
    finally:
        _AUDIT_CTX.reset(token)


def get_audit_context() -> dict[str, Any]:
    try:
        v = _AUDIT_CTX.get()
    except Exception:
        v = {}
    return dict(v or {})


def add_audit_meta(meta: dict[str, Any] | None = None, /, **kwargs: Any) -> None:
    """
    Merge fields into current audit context's meta dict.
    """
    patch: dict[str, Any] = {}
    if isinstance(meta, dict):
        patch.update(meta)
    patch.update(dict(kwargs or {}))
    if not patch:
        return
    prev = get_audit_context()
    cur_meta = prev.get("meta")
    if not isinstance(cur_meta, dict):
        cur_meta = {}
    merged = dict(cur_meta)
    merged.update(patch)
    prev["meta"] = merged
    _AUDIT_CTX.set(prev)


def incr_audit_meta_int(key: str, delta: int | None) -> None:
    """
    Increment an integer field under current audit meta.
    Missing/invalid values are treated as 0.
    """
    if delta is None:
        return
    try:
        d = int(delta)
    except Exception:
        return
    if d == 0:
        return
    ctx = get_audit_context()
    if not ctx:
        return
    meta = ctx.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    try:
        cur = int(meta.get(key) or 0)
    except Exception:
        cur = 0
    meta[key] = cur + d
    ctx["meta"] = meta
    _AUDIT_CTX.set(ctx)
