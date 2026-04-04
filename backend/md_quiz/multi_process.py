from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    command: tuple[str, ...]


def _log(message: str) -> None:
    print(f"[multi-process] {message}", flush=True)


def _build_api_command() -> tuple[str, ...]:
    host = str(os.getenv("APP_HOST", "0.0.0.0") or "0.0.0.0").strip() or "0.0.0.0"
    port = str(os.getenv("PORT", "8000") or "8000").strip() or "8000"
    return (
        sys.executable,
        "-m",
        "uvicorn",
        "backend.md_quiz.main:app",
        "--host",
        host,
        "--port",
        port,
    )


def _process_specs() -> tuple[ProcessSpec, ...]:
    return (
        ProcessSpec(name="api", command=_build_api_command()),
        ProcessSpec(name="worker", command=(sys.executable, "-m", "backend.md_quiz.worker")),
        ProcessSpec(name="scheduler", command=(sys.executable, "-m", "backend.md_quiz.scheduler")),
    )


def _terminate_processes(processes: dict[str, subprocess.Popen[bytes]]) -> None:
    for name, proc in processes.items():
        if proc.poll() is not None:
            continue
        _log(f"stopping {name} pid={proc.pid}")
        proc.terminate()


def _wait_for_shutdown(processes: dict[str, subprocess.Popen[bytes]], *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if all(proc.poll() is not None for proc in processes.values()):
            return
        time.sleep(0.2)
    for name, proc in processes.items():
        if proc.poll() is not None:
            continue
        _log(f"killing {name} pid={proc.pid}")
        proc.kill()


def main() -> int:
    processes: dict[str, subprocess.Popen[bytes]] = {}
    shutting_down = False
    exit_code = 0

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        _log(f"received signal {signum}, shutting down children")
        _terminate_processes(processes)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        for spec in _process_specs():
            _log(f"starting {spec.name}: {' '.join(spec.command)}")
            processes[spec.name] = subprocess.Popen(spec.command)

        while True:
            for name, proc in processes.items():
                code = proc.poll()
                if code is None:
                    continue
                if not shutting_down:
                    shutting_down = True
                    exit_code = code if code != 0 else 1
                    _log(f"{name} exited with code {code}, stopping remaining children")
                    _terminate_processes(processes)
                break
            if shutting_down and all(proc.poll() is not None for proc in processes.values()):
                break
            time.sleep(0.5)
    finally:
        _terminate_processes(processes)
        _wait_for_shutdown(processes, timeout_seconds=10)
        for proc in processes.values():
            try:
                proc.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
