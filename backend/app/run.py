"""Process supervisor for the API and durable publication workers.

One command starts the modular monolith roles without coupling worker lifecycle
into FastAPI startup hooks. Multiple publication workers are safe because job
claims use PostgreSQL ``FOR UPDATE SKIP LOCKED``.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml-supervisor")


def _start(module: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", module, *args])


def _worker_count() -> int:
    settings = get_settings()
    requested = max(1, min(4, int(settings.worker_processes)))
    if settings.cleanup_uploads_after_success and requested > 1:
        logger.warning(
            "worker_processes_capped requested=%d effective=1 reason=cleanup_uploads_after_success",
            requested,
        )
        return 1
    return requested


def run() -> None:
    port = os.getenv("PORT", "8000").strip() or "8000"
    api = _start("uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port)
    workers = [_start("app.worker") for _ in range(_worker_count())]
    logger.info(
        "backend_supervisor_started api_pid=%s worker_pids=%s",
        api.pid,
        ",".join(str(worker.pid) for worker in workers),
    )
    try:
        while True:
            api_code = api.poll()
            if api_code is not None:
                raise RuntimeError(f"FastAPI terminó inesperadamente (exit={api_code}).")

            for index, worker in enumerate(workers):
                worker_code = worker.poll()
                if worker_code is None:
                    continue
                logger.warning(
                    "publication_worker_stopped index=%d exit=%s restarting=true",
                    index,
                    worker_code,
                )
                workers[index] = _start("app.worker")
                logger.info(
                    "publication_worker_restarted index=%d worker_pid=%s",
                    index,
                    workers[index].pid,
                )
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("backend_supervisor_stopping")
    finally:
        processes = [*workers, api]
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    run()
