"""S3-7 缓存基础设施：同步 Redis + 可注入内存实现。

缓存是旁路能力：Redis 连接/命令失败只记 WARNING 并返回 miss，绝不阻断问答。
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Protocol

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get(self, key: str) -> str | None:
        """未命中或缓存不可用时返回 None。"""

    def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        """写入成功返回 True；不可用返回 False。"""

    def delete(self, key: str) -> None:
        """尽力删除；失败不抛异常。"""


class _RedisLike(Protocol):
    def get(self, key: str) -> object: ...

    def set(self, key: str, value: str, ex: int) -> object: ...

    def delete(self, key: str) -> object: ...


class MemoryCache:
    """测试/无 Redis 环境用；TTL 以 monotonic 秒计。"""

    def __init__(self, *, now=time.monotonic) -> None:
        self._now = now
        self._rows: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        row = self._rows.get(key)
        if row is None:
            return None
        value, expires_at = row
        if self._now() >= expires_at:
            self._rows.pop(key, None)
            return None
        return value

    def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return False
        self._rows[key] = (value, self._now() + ttl_seconds)
        return True

    def delete(self, key: str) -> None:
        self._rows.pop(key, None)


class NullCache:
    """CACHE_ENABLED=false 时的 no-op 实现。"""

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        return False

    def delete(self, key: str) -> None:
        return None


class RedisCache:
    def __init__(self, *, client: _RedisLike | None = None) -> None:
        self._client = client
        self._client_created = False

    def _get_client(self) -> _RedisLike | None:
        if self._client is not None:
            return self._client
        if self._client_created:
            return self._client
        settings = get_settings()
        try:
            self._client = redis.Redis.from_url(  # type: ignore[assignment]
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
        except Exception:
            logger.warning("cache_client_init_failed")
            self._client = None
        self._client_created = True
        return self._client

    def _warn(self, op: str) -> None:
        logger.warning("cache_unavailable", extra={"op": op})

    def get(self, key: str) -> str | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            value = client.get(key)
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return value if isinstance(value, str) else None
        except Exception:
            self._warn("get")
            return None

    def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        client = self._get_client()
        if client is None:
            return False
        try:
            return bool(client.set(key, value, ex=ttl_seconds))
        except Exception:
            self._warn("set")
            return False

    def delete(self, key: str) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(key)
        except Exception:
            self._warn("delete")


@lru_cache(maxsize=1)
def get_cache() -> Cache:
    if not get_settings().cache_enabled:
        return NullCache()
    return RedisCache()