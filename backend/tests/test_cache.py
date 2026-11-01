"""S3-7 通用缓存层：TTL 与 Redis 故障 fail-open。"""
from __future__ import annotations

from app.core.cache import MemoryCache, NullCache, RedisCache


class BoomClient:
    def get(self, key: str) -> str:
        raise RuntimeError("redis down")

    def set(self, key: str, value: str, ex: int) -> bool:
        raise RuntimeError("redis down")


class NoDeleteClient:
    def delete(self, key: str) -> int:
        raise RuntimeError("redis down")


def test_memory_cache_honors_ttl() -> None:
    now = [0.0]
    cache = MemoryCache(now=lambda: now[0])
    assert cache.set("k", "v", 10) is True
    assert cache.get("k") == "v"
    now[0] = 10.0
    assert cache.get("k") is None


def test_redis_cache_fail_open_on_get_and_set() -> None:
    cache = RedisCache(client=BoomClient())
    assert cache.get("k") is None
    assert cache.set("k", "v", 10) is False


def test_redis_cache_delete_is_best_effort() -> None:
    RedisCache(client=NoDeleteClient()).delete("k")


def test_null_cache_never_stores() -> None:
    cache = NullCache()
    assert cache.set("k", "v", 10) is False
    assert cache.get("k") is None
    cache.delete("k")