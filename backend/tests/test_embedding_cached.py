"""S3-7 Embedding 内容缓存：命中不调 inner、只编码 miss、顺序保持。"""
from __future__ import annotations

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.cached import CachedEmbeddingClient
from app.core.cache import MemoryCache


class FakeEmbedding(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(model="fake-embed", dim=2)
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        vectors = [[float(len(text)), 1.0] for text in texts]
        if on_batch is not None:
            on_batch(BatchStats(0, 1, len(texts), 10, 1))
        return vectors


def test_cached_embedding_hits_without_inner_call() -> None:
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(), 60)
    first = client.encode(["a", "bb"])
    second = client.encode(["a", "bb"])
    assert first == second == [[1.0, 1.0], [2.0, 1.0]]
    assert inner.calls == [["a", "bb"]]


def test_cached_embedding_only_encodes_misses_in_order() -> None:
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(), 60)
    client.encode(["a"])
    assert client.encode(["a", "bbb", "cc"]) == [
        [1.0, 1.0],
        [3.0, 1.0],
        [2.0, 1.0],
    ]
    assert inner.calls == [["a"], ["bbb", "cc"]]


def test_cached_embedding_bypasses_cache_after_ttl() -> None:
    now = [0.0]
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(now=lambda: now[0]), 5)
    client.encode(["a"])
    now[0] = 6.0
    client.encode(["a"])
    assert inner.calls == [["a"], ["a"]]


def test_cached_embedding_empty_input_does_not_call_inner() -> None:
    inner = FakeEmbedding()
    client = CachedEmbeddingClient(inner, MemoryCache(), 60)
    assert client.encode([]) == []
    assert inner.calls == []