"""S4-4 变式题生成适配器：严格 JSON + Pydantic 校验 + 最多 2 次重试。

只负责「把上下文变成可信的结构化题目」；答案对不对由 `variant_verifier` 独立复算，
比对由 `compare.match_answers` 决定 —— 三件事分开，测试才能分别盯住（spec §5）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.schemas.question import OptionIn, validate_question_shape

logger = logging.getLogger(__name__)

SCENE = "gen"
PROMPT_VERSION = "question_gen_v1"
PROMPT_FILE = "question_gen_v1.md"
MAX_VARIANTS = 3
MAX_RETRIES = 2
STEM_LIMIT = 2000
ANSWER_LIMIT = 800
KP_LIMIT = 3
TEMPERATURE = 0.7

_QTYPES = ("单选", "多选", "填空", "解答")

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class VariantGenerationError(Exception):
    """生成失败：JSON 非法、条数不符、字段非法、重试耗尽。"""


@dataclass(frozen=True)
class GenerationContext:
    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)
    correct_answer_md: str | None = None
    kp_names: list[str] = field(default_factory=list)
    cause_type: str | None = None
    qtype: str = "解答"
    difficulty: int = 3
    count: int = MAX_VARIANTS


class GeneratedVariant(BaseModel):
    stem_md: str = Field(min_length=5, max_length=STEM_LIMIT)
    options: list[OptionIn] | None = None
    answer_md: str = Field(min_length=1, max_length=ANSWER_LIMIT)
    analysis_md: str = Field(min_length=10, max_length=1500)
    qtype: str
    difficulty: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def _check(self) -> "GeneratedVariant":
        if self.qtype not in _QTYPES:
            raise ValueError(f"非法题型：{self.qtype}")
        keys = [option.key for option in self.options] if self.options else None
        validate_question_shape(qtype=self.qtype, option_keys=keys)
        self.stem_md = self.stem_md.strip()
        self.answer_md = self.answer_md.strip()
        self.analysis_md = self.analysis_md.strip()
        return self


class _ItemsOut(BaseModel):
    items: list[GeneratedVariant]


def render_prompt(context: GenerationContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stem_md=context.stem_md[:STEM_LIMIT],
            options=context.options,
            correct_answer_md=(context.correct_answer_md or "")[:ANSWER_LIMIT] or None,
            kp_names=context.kp_names[:KP_LIMIT],
            cause_type=context.cause_type,
            qtype=context.qtype,
            difficulty=context.difficulty,
            count=context.count,
        )
    except Exception as exc:  # 模板缺变量/文件缺失都收敛成生成失败
        raise VariantGenerationError(f"prompt 渲染失败：{exc}") from exc


def generate_variants(
    context: GenerationContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> list[GeneratedVariant]:
    """生成 `context.count` 道题；条数不符或字段非法都按失败重试。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    if context.count < 1:
        raise ValueError("count 必须 ≥1")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(messages, temperature=TEMPERATURE, max_tokens=2000, scene=SCENE)
        try:
            parsed = _ItemsOut.model_validate(loads_json_object(response.text))
            if len(parsed.items) != context.count:
                raise ValueError(f"生成条数不符：{len(parsed.items)} != {context.count}")
            return parsed.items
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("variant_generate_retry attempt=%s error=%s", attempts, exc)
    raise VariantGenerationError(f"变式题生成失败（已尝试 {attempts} 次）：{last_error}")