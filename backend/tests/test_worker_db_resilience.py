import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app import worker


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


def _operational_error():
    return OperationalError("SELECT 1", {}, RuntimeError("connection lost"))


def test_db_retry_delay_is_exponential_and_capped(monkeypatch):
    monkeypatch.setattr(worker.settings, "worker_db_retry_base_seconds", 1.0)
    monkeypatch.setattr(worker.settings, "worker_db_retry_max_seconds", 4.0)

    assert worker._db_retry_delay(1) == 1.0
    assert worker._db_retry_delay(2) == 2.0
    assert worker._db_retry_delay(3) == 4.0
    assert worker._db_retry_delay(8) == 4.0


def test_control_db_action_recovers_without_terminating_worker(monkeypatch):
    calls = {"action": 0, "dispose": 0}
    sleeps = []

    monkeypatch.setattr(worker, "SessionLocal", lambda: _SessionContext(object()))
    monkeypatch.setattr(worker, "reset_connection_pool", lambda: calls.__setitem__("dispose", calls["dispose"] + 1))
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)
    monkeypatch.setattr(worker.settings, "worker_db_retry_base_seconds", 0.5)
    monkeypatch.setattr(worker.settings, "worker_db_retry_max_seconds", 2.0)

    def action(_db):
        calls["action"] += 1
        if calls["action"] == 1:
            raise _operational_error()

    worker._run_control_db_action("heartbeat", action)

    assert calls == {"action": 2, "dispose": 1}
    assert sleeps == [0.5]


def test_claim_job_retries_when_select_connection_is_lost(monkeypatch):
    class BrokenSelectSession:
        def scalar(self, _statement):
            raise _operational_error()

    class EmptyQueueSession:
        def scalar(self, _statement):
            return None

    sessions = iter([BrokenSelectSession(), EmptyQueueSession()])
    disposed = []
    sleeps = []

    monkeypatch.setattr(worker, "SessionLocal", lambda: _SessionContext(next(sessions)))
    monkeypatch.setattr(worker, "reset_connection_pool", lambda: disposed.append(True))
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)
    monkeypatch.setattr(worker.settings, "worker_db_retry_base_seconds", 1.0)
    monkeypatch.setattr(worker.settings, "worker_db_retry_max_seconds", 15.0)

    assert worker.claim_job() is None
    assert len(disposed) == 1
    assert sleeps == [1.0]


def test_claim_job_reconciles_ambiguous_commit(monkeypatch):
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        status=worker.JobStatus.PENDING,
        started_at=None,
        total=3,
    )

    class ClaimSession:
        def scalar(self, _statement):
            return job

        def commit(self):
            raise _operational_error()

    class ReconcileSession:
        def get(self, model, requested_id):
            assert model is worker.Job
            assert requested_id == job_id
            # Simulate PostgreSQL having committed the claim before the socket died.
            return job

    sessions = iter([ClaimSession(), ReconcileSession()])
    disposed = []

    monkeypatch.setattr(worker, "SessionLocal", lambda: _SessionContext(next(sessions)))
    monkeypatch.setattr(worker, "reset_connection_pool", lambda: disposed.append(True))
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)

    claimed = worker.claim_job()

    assert claimed == job_id
    assert job.status == worker.JobStatus.RUNNING
    assert job.started_at is not None
    assert disposed


def test_control_db_action_can_fail_fast_during_shutdown(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", lambda: _SessionContext(object()))
    monkeypatch.setattr(worker, "reset_connection_pool", lambda: None)

    def action(_db):
        raise _operational_error()

    with pytest.raises(OperationalError):
        worker._run_control_db_action("unregister", action, max_attempts=1)
