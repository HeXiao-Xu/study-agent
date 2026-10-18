"""本地 Embedding 占位：后期成本优化时再填（spec §4.1）。

本期明确不引入 sentence-transformers / FlagEmbedding（AGENTS §2），
接口先占位，保证切换厂商不动业务层。
"""
from __future__ import annotations

from collections.abc import Callable

from app.ai.embedding.base import BatchStats, EmbeddingClient


class LocalEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        super().__init__(model="local", dim=0)

    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        raise NotImplementedError("LocalEmbeddingClient 为占位实现：后期成本优化时再填（spec §4.1）")
