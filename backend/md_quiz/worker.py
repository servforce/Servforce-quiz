from __future__ import annotations

import time

from backend.md_quiz.app import _build_container


def main() -> None:
    container = _build_container()
    settings = container.settings
    runtime = container.runtime_service
    jobs = container.job_service
    runtime.heartbeat("worker", name="worker", status="starting", message="worker booting")
    while True:
        runtime.heartbeat("worker", name="worker", status="running", message="polling jobs")
        job = jobs.claim_next("worker")
        if job is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        jobs.process(job)


if __name__ == "__main__":
    main()
