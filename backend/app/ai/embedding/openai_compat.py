"""OpenAI 兼容 Embedding 适配器：默认服务 DashScope（spec §4.2）。

为什么手写重试而不是用 openai SDK：项目只依赖 httpx，重试/退避/维度校验
需要完全可控；SDK 会引入额外依赖与隐式重试。
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

from app.ai.embedding.base import BatchStats, EmbeddingClient
from app.ai.embedding.errors import EmbeddingError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dim: int,
        batch_size: int = 10,
        timeout: float = 60.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(model=model, dim=dim)
        if not api_key:
            raise EmbeddingError(
                "EMBEDDING_API_KEY / DASHSCOPE_API_KEY 未配置：请在仓库根 .env 填入 Key（spec §9.1）",
                provider="openai_compat",
            )
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleEmbeddingClient(model={self.model!r}, dim={self.dim}, "
            f"url={self._url!r})"
        )

    def close(self) -> None:
        self._http.close()

    def encode(
        self,
        texts: list[str],
        *,
        on_batch: Callable[[BatchStats], None] | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []
        batches = [texts[i : i + self._batch_size] for i in range(0, len(texts), self._batch_size)]
        vectors: list[list[float]] = []
        for batch_index, batch in enumerate(batches):
            started = time.perf_counter()
            payload = self._post_with_retry(batch, batch_index=batch_index)
            vectors.extend(self._parse_vectors(payload, expected=len(batch)))
            latency_ms = int((time.perf_counter() - started) * 1000)
            tokens = int((payload.get("usage") or {}).get("total_tokens", 0))
            self.usage_tokens += tokens
            logger.info(
                "embedding_call",
                extra={
                    "scene": "embed",
                    "model": self.model,
                    "batch_index": batch_index,
                    "batch_size": len(batch),
                    "tokens": tokens,
                    "latency_ms": latency_ms,
                },
            )
            if on_batch is not None:
                on_batch(
                    BatchStats(
                        batch_index=batch_index,
                        batch_count=len(batches),
                        batch_size=len(batch),
                        tokens=tokens,
                        latency_ms=latency_ms,
                    )
                )
        return vectors

    def _post_with_retry(self, batch: list[str], *, batch_index: int) -> dict:
        payload = {
            "model": self.model,
            "input": batch,
            "dimensions": self.dim,
            "encoding_format": "float",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise EmbeddingError(
                        f"Embedding 网络错误（重试耗尽）：{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                delay = self._backoff(attempt, None)
                logger.warning(
                    "embedding_retry",
                    extra={"attempt": attempt + 1, "reason": type(exc).__name__, "delay_s": delay},
                )
                self._sleep(delay)
                continue
            self.request_count += 1
            if response.status_code < 400:
                return self._json_or_raise(response)
            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    raise EmbeddingError(
                        f"Embedding 请求重试耗尽（HTTP {response.status_code}）",
                        status_code=response.status_code,
                        retryable=True,
                    )
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "embedding_retry",
                    extra={
                        "attempt": attempt + 1,
                        "status": response.status_code,
                        "delay_s": delay,
                    },
                )
                self._sleep(delay)
                continue
            raise EmbeddingError(
                f"Embedding 请求失败：HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
                retryable=False,
            )
        raise EmbeddingError("Embedding 请求失败：未知重试状态", retryable=False)

    @staticmethod
    def _json_or_raise(response: httpx.Response) -> dict:
        try:
            return response.json()
        except ValueError as exc:
            raise EmbeddingError("Embedding 响应不是合法 JSON", retryable=False) from exc

    def _parse_vectors(self, payload: dict, *, expected: int) -> list[list[float]]:
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingError(
                f"Embedding 返回条数不符：期望 {expected}，实际 {len(data) if isinstance(data, list) else '非列表'}",
                retryable=False,
            )
        items = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for item in items:
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dim:
                actual = len(vector) if isinstance(vector, list) else "非列表"
                raise EmbeddingError(
                    f"Embedding 维度不符：期望 {self.dim}，实际 {actual}（spec §4.4 停止并报告）",
                    retryable=False,
                )
            vectors.append([float(value) for value in vector])
        return vectors

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        base = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
        return base + random.uniform(0, base * 0.25)
