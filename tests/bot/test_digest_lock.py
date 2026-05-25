import asyncio

import pytest

from aggregator.bot.digest_lock import lock_for, _topic_locks


@pytest.fixture(autouse=True)
def clean_locks():
    _topic_locks.clear()
    yield
    _topic_locks.clear()


def test_lock_for_returns_same_instance_for_same_topic():
    a = lock_for("crypto_general")
    b = lock_for("crypto_general")
    assert a is b


def test_lock_for_returns_different_instances_for_different_topics():
    a = lock_for("crypto_general")
    b = lock_for("ai_general")
    assert a is not b


@pytest.mark.asyncio
async def test_lock_is_an_asyncio_lock():
    lock = lock_for("crypto_general")
    assert isinstance(lock, asyncio.Lock)
    assert not lock.locked()
    async with lock:
        assert lock.locked()
    assert not lock.locked()
