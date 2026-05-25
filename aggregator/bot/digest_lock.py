"""Per-topic asyncio.Lock registry.

Shared between the scheduler (`aggregator.scheduler._job`) and `/digest`
so a manual digest cannot race a scheduled one for the same topic.
Locks are created lazily and live for the lifetime of the process.
"""
from __future__ import annotations

import asyncio

_topic_locks: dict[str, asyncio.Lock] = {}


def lock_for(topic_id: str) -> asyncio.Lock:
    lock = _topic_locks.get(topic_id)
    if lock is None:
        lock = asyncio.Lock()
        _topic_locks[topic_id] = lock
    return lock
