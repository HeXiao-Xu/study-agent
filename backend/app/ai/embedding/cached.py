"""S3-7 Embedding 内容哈希缓存包装器。

只把 miss 的文本交给厂商；命中不产生厂商调用，也不产生调用日志。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.errors import EmbeddingError
from app.core.cache import Cache


class CachedEmbeddingClient(EmbeddingClient):
    def __init__(
        self, inner: EmbeddingClient, cache: Cache, ttl_seconds: int
    ) -> None:
        super().__init__(model=inner.model, dim=inner.dim)
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_seconds

    def _key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"embed:{self.model}:{self.dim}:{digest}"

    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        keys = [self._key(text) for text in texts]
        vectors: list[list[float] | None] = [None] * len(texts)
        miss_indexes: list[int] = []
        for index, key in enumerate(keys):
            raw = self._cache.get(key)
            cached = self._load_cached(raw) if raw is not None else None
            if cached is not None:
                vectors[index] = cached
                continue
            miss_indexes.append(index)

        if miss_indexes:
            miss_texts = [texts[index] for index in miss_indexes]
            fresh = self._inner.encode(miss_texts, on_batch=on_batch)
            if len(fresh) != len(miss_texts):
                raise EmbeddingError(
                    "Embedding 返回条数不符："
                    f"期望 {len(miss_texts)}，实际 {len(fresh)}",
                    retryable=False,
                )
            for index, vector in zip(miss_indexes, fresh):
                if len(vector) != self.dim:
                    raise EmbeddingError(
                        f"第 {index} 条向量维度不符：期望 {self.dim}，实际 {len(vector)}",
                        retryable=False,
                    )
                vectors[index] = vector
                self._cache.set(keys[index], json.dumps(vector), self._ttl)

        if any(vector is None for vector in vectors):
            raise EmbeddingError("Embedding 结果缺失", retryable=False)
        return [vector for vector in vectors if vector is not None]

    def _load_cached(self, raw: str) -> list[float] | None:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, list) or len(value) != self.dim:
            return None
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None