"""S1-6 LLM 门面：业务层只 import 这里。"""
from __future__ import annotations

from functools import lru_cache

from app.ai.llm.base import LLMClient, LLMMessage, LLMResponse
from app.ai.llm.errors import LLMError
from app.ai.llm.openai_compat import OpenAICompatibleLLMClient
from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
        price_input_per_million=settings.llm_price_input_per_million,
        price_output_per_million=settings.llm_price_output_per_million,
    )


__all__ = [
    "LLMClient",
    "LLMError",
    "LLMMessage",
    "LLMResponse",
    "OpenAICompatibleLLMClient",
    "get_llm_client",
]