"""OpenAI 兼容 /chat/completions 适配器（S1-6，默认 DashScope qwen-plus）。

错误信息只保留状态码/异常类型；厂商响应正文、Prompt、Key 一律不进异常/日志。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "qwen-plus",
        timeout: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.3,
        max_output_tokens: int = 1200,
        price_input_per_million: float = 0.8,
        price_output_per_million: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(model=model)
        if not api_key:
            raise LLMError("LLM_API_KEY 未配置", retryable=False)
        if not base_url:
            raise LLMError("LLM_BASE_URL 未配置", retryable=False)
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._price_in = price_input_per_million
        self._price_out = price_output_per_million
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("messages 不能为空")
        payload = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
        }
        started = time.perf_counter()
        data = self._post_with_retry(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = self._extract_text(data)
        prompt_tokens, completion_tokens, total_tokens = self._parse_usage(data)
        cost = (
            prompt_tokens * self._price_in / 1_000_000
            + completion_tokens * self._price_out / 1_000_000
        )
        self.usage_tokens += total_tokens
        self.request_count += 1
        logger.info(
            "llm_call",
            extra={
                "scene": "qa",
                "model": self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "cost_yuan": round(cost, 8),
            },
        )
        return LLMResponse(
            text=text,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_yuan=cost,
        )

    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise LLMError(
                        f"LLM 网络错误（重试耗尽）：{type(exc).__name__}",
                        retryable=True,
                    ) from exc
                self._sleep(self._backoff(attempt, None))
                continue

            status = response.status_code
            if 200 <= status < 300:
                return self._json_object(response)
            if status in _RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep(self._backoff(attempt, response))
                continue
            raise LLMError(
                f"LLM 请求失败：HTTP {status}",
                status_code=status,
                retryable=status in _RETRYABLE_STATUS,
            )

        raise LLMError("LLM 请求失败：未知重试状态", retryable=True)

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError("LLM 返回非 JSON", retryable=False) from exc
        if not isinstance(payload, dict):
            raise LLMError("LLM 响应顶层不是对象", retryable=False)
        return payload

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("LLM 响应缺少 choices", retryable=False)
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMError("LLM choices[0] 不是对象", retryable=False)
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMError("LLM 响应缺少 message", retryable=False)
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回空回答", retryable=False)
        return content.strip()

    @staticmethod
    def _parse_usage(data: dict[str, Any]) -> tuple[int, int, int]:
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return 0, 0, 0

        def _int(value: object) -> int:
            try:
                number = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0
            return max(0, number)

        prompt = _int(usage.get("prompt_tokens"))
        completion = _int(usage.get("completion_tokens"))
        total_raw = usage.get("total_tokens")
        total = _int(total_raw) if total_raw is not None else prompt + completion
        return prompt, completion, total

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    pass
        return min(2.0**attempt, 8.0)

    def close(self) -> None:
        self._client.close()

    def __repr__(self) -> str:
        return f"OpenAICompatibleLLMClient(model={self.model!r}, url={self._url!r})"