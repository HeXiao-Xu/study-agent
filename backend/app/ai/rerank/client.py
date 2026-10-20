"""S1-5 Rerank 适配器：DashScope qwen3-rerank + 本地占位（spec §5）。

截断/重试/解析/降级全部在适配器边界处理；业务层只依赖 RerankClient。
"""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
import tiktoken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF_SECONDS = 30.0
_MAX_DOCUMENTS = 500
_encoding: tiktoken.Encoding | None = None


class RerankError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        provider: str = "dashscope",
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class RerankCandidate:
    id: int
    content: str


@dataclass(frozen=True)
class RerankScore:
    id: int
    score: float


@dataclass(frozen=True)
class RerankResponse:
    model: str
    scores: list[RerankScore] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0


class RerankClient(ABC):
    model: str

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        """一次请求重排全部候选；返回按 score 降序的 [(id, score)]。"""


class LocalRerankClient(RerankClient):
    model = "local"

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        raise RerankError(
            "LocalRerankClient 为占位实现：本次不引入本地重排模型",
            provider="local",
            retryable=False,
        )


def _encoding_get() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    try:
        enc = _encoding_get()
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text, False
        return enc.decode(tokens[:max_tokens]), True
    except Exception as exc:
        # tiktoken 首次加载 BPE 可能需要网络/缓存；失败必须可降级，不能把检索打挂
        raise RerankError(
            f"Rerank tokenizer 不可用（{type(exc).__name__}）",
            retryable=True,
        ) from exc


class DashScopeRerankClient(RerankClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen3-rerank",
        timeout: float = 30.0,
        max_retries: int = 2,
        max_doc_tokens: int = 3600,
        price_per_million: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise RerankError(
                "RERANK_API_KEY / DASHSCOPE_API_KEY 未配置：请在仓库根 .env 填入 Key（spec §5.6）",
                provider="dashscope",
            )
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/services/rerank/text-rerank/text-rerank"
        self._max_retries = max_retries
        self._max_doc_tokens = max_doc_tokens
        self._price_per_million = price_per_million
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self.request_count = 0
        self.usage_tokens = 0

    def __repr__(self) -> str:
        return f"DashScopeRerankClient(model={self.model!r}, url={self._url!r})"

    def close(self) -> None:
        self._http.close()

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> RerankResponse:
        if top_n is not None and top_n <= 0:
            raise ValueError("top_n 必须为正整数")
        if not candidates:
            return RerankResponse(model=self.model)
        if len(candidates) > _MAX_DOCUMENTS:
            raise RerankError(
                f"候选数 {len(candidates)} 超过厂商上限 {_MAX_DOCUMENTS}",
                retryable=False,
            )

        started = time.perf_counter()
        query_text, query_truncated = _truncate_to_tokens(query, self._max_doc_tokens)
        documents: list[str] = []
        documents_truncated = 0
        for candidate in candidates:
            text, truncated = _truncate_to_tokens(candidate.content, self._max_doc_tokens)
            documents.append(text)
            documents_truncated += int(truncated)
        if query_truncated or documents_truncated:
            logger.warning(
                "rerank_truncated",
                extra={
                    "scene": "rerank",
                    "query_truncated": query_truncated,
                    "documents_truncated": documents_truncated,
                    "max_doc_tokens": self._max_doc_tokens,
                },
            )

        effective_top_n = min(top_n or len(candidates), len(candidates))
        payload = {
            "model": self.model,
            "input": {"query": query_text, "documents": documents},
            "parameters": {"return_documents": False, "top_n": effective_top_n},
        }
        response_payload = self._post_with_retry(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        tokens = self._parse_tokens(response_payload)
        self.usage_tokens += tokens
        cost_yuan = tokens * self._price_per_million / 1_000_000
        scores = self._parse_scores(response_payload, candidates=candidates)
        if len(scores) < effective_top_n:
            raise RerankError(
                f"Rerank 返回结果不完整：期望 {effective_top_n}，实际 {len(scores)}",
                retryable=False,
            )

        logger.info(
            "rerank_call",
            extra={
                "scene": "rerank",
                "model": self.model,
                "candidates": len(candidates),
                "top_n": effective_top_n,
                "tokens": tokens,
                "latency_ms": latency_ms,
                "cost_yuan": cost_yuan,
                "truncated": query_truncated or documents_truncated > 0,
            },
        )
        return RerankResponse(
            model=self.model,
            scores=scores,
            tokens=tokens,
            latency_ms=latency_ms,
            cost_yuan=cost_yuan,
        )

    def _post_with_retry(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self._max_retries:
                    raise RerankError(
                        f"Rerank 网络错误（重试耗尽）：{type(exc).__name__}: {exc}",
                        retryable=True,
                    ) from exc
                delay = self._backoff(attempt, None)
                logger.warning(
                    "rerank_retry",
                    extra={"attempt": attempt + 1, "reason": type(exc).__name__, "delay_s": delay},
                )
                self._sleep(delay)
                continue

            self.request_count += 1
            if 200 <= response.status_code < 300:
                payload_json = self._json_or_raise(response)
                if not isinstance(payload_json, dict):
                    raise RerankError("Rerank 响应顶层不是对象", retryable=False)
                return payload_json
            if response.status_code in _RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    raise RerankError(
                        f"Rerank 请求重试耗尽（HTTP {response.status_code}）",
                        status_code=response.status_code,
                        retryable=True,
                    )
                delay = self._backoff(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "rerank_retry",
                    extra={
                        "attempt": attempt + 1,
                        "status": response.status_code,
                        "delay_s": delay,
                    },
                )
                self._sleep(delay)
                continue
            raise RerankError(
                f"Rerank 请求失败：HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=False,
            )
        raise RerankError("Rerank 请求失败：未知重试状态", retryable=False)

    @staticmethod
    def _json_or_raise(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise RerankError("Rerank 响应不是合法 JSON", retryable=False) from exc

    @staticmethod
    def _parse_tokens(payload: dict) -> int:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return 0
        raw_tokens = usage.get("total_tokens", 0)
        try:
            return max(int(raw_tokens), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_scores(payload: dict, *, candidates: list[RerankCandidate]) -> list[RerankScore]:
        output = payload.get("output")
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list) or not results:
            raise RerankError("Rerank 响应缺少 output.results 或为空", retryable=False)

        parsed: list[tuple[int, float]] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise RerankError("Rerank 响应结果项不是对象", retryable=False)
            index = item.get("index")
            score = item.get("relevance_score")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index < 0
                or index >= len(candidates)
            ):
                raise RerankError(f"Rerank 返回 index 越界：{index!r}", retryable=False)
            if index in seen:
                raise RerankError(f"Rerank 返回重复 index：{index}", retryable=False)
            seen.add(index)
            try:
                value = float(score)
            except (TypeError, ValueError) as exc:
                raise RerankError(f"Rerank 返回非法分数：{score!r}", retryable=False) from exc
            if value != value or value in (float("inf"), float("-inf")):
                raise RerankError(f"Rerank 返回非有限分数：{score!r}", retryable=False)
            parsed.append((index, value))

        parsed.sort(key=lambda item: (-item[1], item[0]))
        return [RerankScore(id=candidates[index].id, score=value) for index, value in parsed]

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), _MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        base = min(2.0**attempt, _MAX_BACKOFF_SECONDS)
        return base + random.uniform(0, base * 0.25)


@lru_cache
def get_rerank_client() -> RerankClient:
    """按配置返回单例；Key 缺失时构造阶段抛 RerankError，由 retriever 回退。"""
    settings = get_settings()
    if settings.rerank_provider == "local":
        return LocalRerankClient()
    return DashScopeRerankClient(
        api_key=settings.rerank_api_key,
        base_url=settings.rerank_base_url,
        model=settings.rerank_model,
        timeout=settings.rerank_timeout_seconds,
        max_retries=settings.rerank_max_retries,
        max_doc_tokens=settings.rerank_max_doc_tokens,
        price_per_million=settings.rerank_price_per_million,
    )