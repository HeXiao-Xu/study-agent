"""S4-4 独立复算适配器：只给题干与选项，让模型自己解一遍。

这是自检的独立侧：Prompt 里不出现参考答案（否则等于让模型给自己打分）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)

SCENE = "gen"
VERIFY_PROMPT_VERSION = "question_verify_v1"
PROMPT_FILE = "question_verify_v1.md"
MAX_RETRIES = 2
STEM_LIMIT = 2000
ANSWER_LIMIT = 500
TEMPERATURE = 0.2

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class VariantVerificationError(Exception):
    """复算失败：JSON 非法、字段缺失、重试耗尽。"""


@dataclass(frozen=True)
class VerifyContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)


class _VerifyOut(BaseModel):
    answer_md: str = Field(min_length=1, max_length=ANSWER_LIMIT)
    reasoning_md: str | None = Field(default=None, max_length=1500)


def render_verify_prompt(context: VerifyContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(stem_md=context.stem_md[:STEM_LIMIT], options=context.options)
    except Exception as exc:
        raise VariantVerificationError(f"验证 prompt 渲染失败：{exc}") from exc


def verify_answer(
    context: VerifyContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> str:
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_verify_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(messages, temperature=TEMPERATURE, max_tokens=1200, scene=SCENE)
        try:
            parsed = _VerifyOut.model_validate(loads_json_object(response.text))
            return parsed.answer_md.strip()
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("variant_verify_retry attempt=%s error=%s", attempts, exc)
    raise VariantVerificationError(f"复算失败（已尝试 {attempts} 次）：{last_error}")