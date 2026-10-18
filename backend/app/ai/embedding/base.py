"""Embedding 适配器契约：可替换厂商，业务层只依赖这个抽象（spec §4）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BatchStats:
    """单批进度：给 demo 打印与日志用，不参与返回向量。"""

    batch_index: int
    batch_count: int
    batch_size: int
    tokens: int
    latency_ms: int


class EmbeddingClient(ABC):
    def __init__(self, *, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self.usage_tokens = 0  # 累计 token，服务层做差值得本次用量
        self.request_count = 0  # 含重试的 HTTP 请求数

    @abstractmethod
    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        """文本列表 → 向量列表；顺序必须与输入一致。"""
