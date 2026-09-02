import pytest
from fastapi import FastAPI

import aijaa.api.app as app_module
from aijaa.core.config import get_settings
from aijaa.orchestration import redis_queue


class FakeRedis:
    def __init__(self, fail_ping: bool = False):
        self.fail_ping = fail_ping
        self.ping_calls = 0
        self.closed = False

    async def ping(self):
        self.ping_calls += 1
        if self.fail_ping:
            raise ConnectionError("redis unavailable")
        return True

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def fake_prepare_database():
    return None


async def test_sync_lifespan_does_not_connect_to_redis(monkeypatch):
    monkeypatch.setenv("AIJAA_WORKFLOW_MODE", "sync")
    monkeypatch.setattr(app_module, "prepare_database", fake_prepare_database)

    async def unexpected_create_pool():
        raise AssertionError("Redis must not be opened in sync mode")

    monkeypatch.setattr(redis_queue, "create_queue_pool", unexpected_create_pool)

    app = FastAPI()

    async with app_module.lifespan(app):
        assert app.state.redis is None

    assert app.state.redis is None


async def test_queue_lifespan_opens_pings_and_closes_redis(monkeypatch):
    monkeypatch.setenv("AIJAA_WORKFLOW_MODE", "queue")
    monkeypatch.setattr(app_module, "prepare_database", fake_prepare_database)

    redis = FakeRedis()

    async def fake_create_pool():
        return redis

    monkeypatch.setattr(redis_queue, "create_queue_pool", fake_create_pool)

    app = FastAPI()

    async with app_module.lifespan(app):
        assert app.state.redis is redis
        assert redis.ping_calls == 1
        assert redis.closed is False

    assert redis.closed is True
    assert app.state.redis is None


async def test_queue_lifespan_fails_and_closes_when_redis_ping_fails(monkeypatch):
    monkeypatch.setenv("AIJAA_WORKFLOW_MODE", "queue")
    monkeypatch.setattr(app_module, "prepare_database", fake_prepare_database)

    redis = FakeRedis(fail_ping=True)

    async def fake_create_pool():
        return redis

    monkeypatch.setattr(redis_queue, "create_queue_pool", fake_create_pool)

    app = FastAPI()

    with pytest.raises(ConnectionError, match="redis unavailable"):
        async with app_module.lifespan(app):
            pass

    assert redis.closed is True
    assert app.state.redis is None
