from __future__ import annotations

from backend.md_quiz.models import ProcessHeartbeat
from backend.md_quiz.storage.db import list_process_heartbeats, upsert_process_heartbeat


class ProcessStore:
    def upsert(self, heartbeat: ProcessHeartbeat) -> ProcessHeartbeat:
        raw = upsert_process_heartbeat(heartbeat.model_dump())
        return ProcessHeartbeat.model_validate(raw)

    def list(self) -> list[ProcessHeartbeat]:
        return [ProcessHeartbeat.model_validate(item) for item in list_process_heartbeats()]


__all__ = ["ProcessStore"]
