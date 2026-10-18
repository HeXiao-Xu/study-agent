"""Embedding 专用异常：不携带 Key，不吞厂商错误上下文。"""
from __future__ import annotations


class EmbeddingError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "openai_compat",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
