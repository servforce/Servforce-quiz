from __future__ import annotations

import os
from datetime import UTC, datetime

from backend.md_quiz.models import ProcessHeartbeat, RuntimeConfig
from backend.md_quiz.storage import JsonProcessStore, JsonRuntimeConfigStore


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RuntimeService:
    def __init__(
        self,
        *,
        process_store: JsonProcessStore,
        runtime_config_store: JsonRuntimeConfigStore,
    ):
        self.process_store = process_store
        self.runtime_config_store = runtime_config_store

    def heartbeat(
        self,
        process: str,
        *,
        name: str,
        status: str = "running",
        message: str = "",
    ) -> ProcessHeartbeat:
        heartbeat = ProcessHeartbeat(
            process=process, name=name, pid=os.getpid(), status=status, message=message, updated_at=_utc_now()
        )
        return self.process_store.upsert(heartbeat)

    def list_processes(self) -> list[ProcessHeartbeat]:
        return self.process_store.list()

    def get_runtime_config(self) -> RuntimeConfig:
        return self.runtime_config_store.load()

    def update_runtime_config(self, payload: dict) -> RuntimeConfig:
        current = self.get_runtime_config()
        config = current.model_copy(update=payload)
        return self.runtime_config_store.save(config)
