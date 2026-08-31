from datetime import timedelta

from app.core.time import utcnow
from app.worker_runtime import heartbeat_is_fresh


def test_worker_heartbeat_is_fresh_inside_threshold():
    now = utcnow()
    assert heartbeat_is_fresh(
        now - timedelta(seconds=5),
        now=now,
        stale_after_seconds=30,
    )


def test_worker_heartbeat_is_stale_after_threshold():
    now = utcnow()
    assert not heartbeat_is_fresh(
        now - timedelta(seconds=31),
        now=now,
        stale_after_seconds=30,
    )
