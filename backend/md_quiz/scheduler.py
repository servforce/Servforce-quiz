from __future__ import annotations

import time
from datetime import UTC, datetime

from backend.md_quiz.app import _build_container
from backend.md_quiz.services import runtime_bootstrap


def main() -> None:
    runtime_bootstrap.bootstrap_runtime()
    container = _build_container()
    settings = container.settings
    runtime = container.runtime_service
    jobs = container.job_service
    runtime.heartbeat("scheduler", name="scheduler", status="starting", message="scheduler booting")
    last_metrics_tick = 0
    while True:
        now = datetime.now(UTC).timestamp()
        runtime.heartbeat("scheduler", name="scheduler", status="running", message="checking timers")
        if now - last_metrics_tick >= settings.scheduler_metrics_interval_seconds:
            jobs.enqueue("sync_metrics", source="scheduler")
            last_metrics_tick = now
        time.sleep(settings.scheduler_poll_seconds)


if __name__ == "__main__":
    main()
