"""Process supervisor for the API and publication worker.

One command starts both durable roles without coupling the worker lifecycle to
FastAPI startup hooks. The API binds to ``0.0.0.0:$PORT`` when deployed and
falls back to port 8000 for local development.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml-supervisor")


def _start(module: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", module, *args])


def run() -> None:
    port = os.getenv("PORT", "8000").strip() or "8000"
    api = _start("uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port)
    worker = _start("app.worker")
    logger.info("backend_supervisor_started api_pid=%s worker_pid=%s", api.pid, worker.pid)
    try:
        while True:
            api_code = api.poll()
            worker_code = worker.poll()
            if api_code is not None:
                raise RuntimeError(f"FastAPI terminó inesperadamente (exit={api_code}).")
            if worker_code is not None:
                logger.warning("publication_worker_stopped exit=%s restarting=true", worker_code)
                worker = _start("app.worker")
                logger.info("publication_worker_restarted worker_pid=%s", worker.pid)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("backend_supervisor_stopping")
    finally:
        for process in (worker, api):
            if process.poll() is None:
                process.terminate()
        for process in (worker, api):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    run()
