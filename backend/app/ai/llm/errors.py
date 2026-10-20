"""S1-6 LLM 错误：不携带响应正文，避免 Prompt/正文回显。"""
from __future__ import annotations


class LLMError(RuntimeError):
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