"""Embedding 门面：全项目唯一获取客户端的入口（spec §4）。"""
from __future__ import annotations

from functools import lru_cache

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.errors import EmbeddingError
from app.ai.embedding.local import LocalEmbeddingClient
from app.ai.embedding.openai_compat import OpenAICompatibleEmbeddingClient
from app.core.config import get_settings

__all__ = [
    "BatchStats",
    "EmbeddingClient",
    "EmbeddingError",
    "LocalEmbeddingClient",
    "OpenAICompatibleEmbeddingClient",
    "get_embedding_client",
]


@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()
    if settings.embedding_provider == "local":
        return LocalEmbeddingClient()
    return OpenAICompatibleEmbeddingClient(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        timeout=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
