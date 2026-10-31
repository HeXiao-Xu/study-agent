"""S1-6 LLM 契约：Answerer 只依赖本文件，不直接依赖 httpx/厂商。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_yuan: float = 0.0


@dataclass(frozen=True)
class LLMStreamChunk:
    """流式片段：text 为增量；response 只在最后一块出现。"""

    text: str = ""
    response: LLMResponse | None = None


class LLMClient(ABC):
    def __init__(self, *, model: str) -> None:
        self.model = model
        self.usage_tokens = 0
        self.request_count = 0

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> LLMResponse:
        """发送一轮对话；网络重试由实现负责，逻辑重试由调用方负责。"""

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        scene: str = "qa",
    ) -> Iterator[LLMStreamChunk]:
        """默认降级：不支持流式的 Client 只产出一次完整文本 + 最终响应。"""
        response = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            scene=scene,
        )
        if response.text:
            yield LLMStreamChunk(text=response.text)
        yield LLMStreamChunk(response=response)