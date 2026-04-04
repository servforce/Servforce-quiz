from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JobStatus = Literal["pending", "running", "done", "failed"]
ProcessKind = Literal["api", "worker", "scheduler"]


class RuntimeConfig(BaseModel):
    token_daily_threshold: int = 500000
    sms_daily_threshold: int = 500
    allow_public_assignments: bool = True
    min_submit_seconds: int = 60
    ui_theme_name: str = "blue-green"


class JobRecord(BaseModel):
    id: str
    kind: str
    source: str = "manual"
    status: JobStatus = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    error: str | None = None
    result: dict[str, Any] | None = None
    worker_name: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ProcessHeartbeat(BaseModel):
    process: ProcessKind
    name: str
    pid: int
    status: Literal["starting", "running", "stopped", "error"] = "running"
    message: str = ""
    updated_at: str
