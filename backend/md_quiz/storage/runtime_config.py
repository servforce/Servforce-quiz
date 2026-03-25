from __future__ import annotations

from backend.md_quiz.models import RuntimeConfig
from backend.md_quiz.storage.db import get_runtime_kv, set_runtime_kv


class RuntimeConfigStore:
    def __init__(self, defaults: RuntimeConfig):
        self.defaults = defaults

    def load(self) -> RuntimeConfig:
        payload = self.defaults.model_dump()
        current = get_runtime_kv("runtime_config") or {}
        if isinstance(current, dict):
            payload.update(current)
        return RuntimeConfig.model_validate(payload)

    def save(self, config: RuntimeConfig) -> RuntimeConfig:
        set_runtime_kv("runtime_config", config.model_dump())
        return config


__all__ = ["RuntimeConfigStore"]
