from __future__ import annotations

from dataclasses import dataclass

from app import run as run_module


@dataclass
class _ProcessStub:
    pid: int
    exit_code: int | None = None
    terminated: bool = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout: int) -> int:
        return self.exit_code or 0

    def kill(self) -> None:
        self.exit_code = -9


def test_supervisor_starts_uvicorn_without_reload(monkeypatch):
    monkeypatch.setenv("PORT", "10000")
    calls: list[tuple[str, tuple[str, ...]]] = []
    processes = [_ProcessStub(pid=101), _ProcessStub(pid=202), _ProcessStub(pid=303)]

    def fake_start(module: str, *args: str) -> _ProcessStub:
        calls.append((module, args))
        return processes[len(calls) - 1]

    def stop_loop(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "_start", fake_start)
    monkeypatch.setattr(run_module.time, "sleep", stop_loop)

    run_module.run()

    assert calls[0] == (
        "uvicorn",
        ("app.main:app", "--host", "0.0.0.0", "--port", "10000"),
    )
    assert calls[1] == ("app.worker", ())
    assert calls[2] == ("app.worker", ())
    assert processes[0].terminated is True
    assert processes[1].terminated is True
    assert processes[2].terminated is True
