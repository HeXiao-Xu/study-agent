"""S4-3 错因诊断适配器：严格 JSON + Pydantic 校验 + 最多 2 次重试。

分层职责：
- render_prompt 只负责拼上下文（Jinja2 StrictUndefined，缺变量直接炸）；
- analyze_mistake 负责调用/重试，把「模型说了什么」变成「Pydantic 认可的什么」；
- _enforce_rules 负责 spec D-4 / D-13 的硬规则（缺作答强制 unknown、error_step 必须有证据），
  这三件事分开，测试才能分别盯住。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.models.enums import CauseType

logger = logging.getLogger(__name__)

# scene 必须落在 llm_call_logs.scene 的 CHECK 白名单内（S4-2 C1：写错就会被静默丢弃）
SCENE = "mistake"

PROMPT_VERSION = "mistake_analyze_v1"
PROMPT_FILE = "mistake_analyze_v1.md"
MAX_RETRIES = 2
STEM_LIMIT = 2000
ANSWER_LIMIT = 800
STUDENT_LIMIT = 1500
NOTE_LIMIT = 200

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class MistakeAnalysisError(Exception):
    """诊断失败：JSON 非法、字段非法、Prompt 渲染失败、重试耗尽。"""


@dataclass(frozen=True)
class DiagnosisContext:
    """诊断所需的全部上下文；笔记片段是 (标题, 摘要) 二元组。"""

    stem_md: str
    options: list[tuple[str, str]] = field(default_factory=list)
    correct_answer_md: str | None = None
    my_answer_md: str | None = None
    kp_names: list[str] = field(default_factory=list)
    prerequisite_names: list[str] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)


class MistakeAnalysisResult(BaseModel):
    cause_type: CauseType
    secondary_causes: list[CauseType] = Field(default_factory=list)
    error_step: str | None = None
    explanation_md: str = Field(min_length=20)
    review_advice_md: str = Field(min_length=10)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("secondary_causes", mode="before")
    @classmethod
    def _coerce_causes(cls, value: Any) -> Any:
        # 模型偶尔返回 null 或 ""，统一成空列表再交给后续校验
        return value or []

    @model_validator(mode="after")
    def _normalize(self) -> "MistakeAnalysisResult":
        seen: list[CauseType] = []
        for cause in self.secondary_causes:
            if cause == self.cause_type or cause == CauseType.UNKNOWN:
                continue
            if cause not in seen:
                seen.append(cause)
        self.secondary_causes = seen[:2]
        if self.cause_type == CauseType.UNKNOWN:
            self.secondary_causes = []
            self.error_step = None
        else:
            self.error_step = (self.error_step or "").strip() or None
        self.explanation_md = self.explanation_md.strip()
        self.review_advice_md = self.review_advice_md.strip()
        return self


def render_prompt(context: DiagnosisContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stem_md=context.stem_md[:STEM_LIMIT],
            options=context.options,
            correct_answer_md=(context.correct_answer_md or "")[:ANSWER_LIMIT] or None,
            my_answer_md=(context.my_answer_md or "")[:STUDENT_LIMIT] or None,
            kp_names=context.kp_names,
            prerequisite_names=context.prerequisite_names,
            notes=[(title, snippet[:NOTE_LIMIT]) for title, snippet in context.notes],
        )
    except Exception as exc:  # 模板缺变量/文件缺失都收敛成诊断失败
        raise MistakeAnalysisError(f"prompt 渲染失败：{exc}") from exc


def analyze_mistake(
    context: DiagnosisContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> MistakeAnalysisResult:
    """一次诊断：渲染 → 调用 → 解析校验 → 硬规则；失败重试 max_retries 次。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(
            messages, temperature=0.2, max_tokens=2000, scene=SCENE
        )
        try:
            payload = loads_json_object(response.text)
            result = MistakeAnalysisResult.model_validate(payload)
            return _enforce_rules(result, context)
        except (ValidationError, ValueError) as exc:
            last_error = exc
    raise MistakeAnalysisError(f"诊断失败（已尝试 {attempts} 次）：{last_error}")


def _enforce_rules(
    result: MistakeAnalysisResult, context: DiagnosisContext
) -> MistakeAnalysisResult:
    """把 spec D-4 / D-13 的硬规则放在代码层，不依赖模型自觉。"""
    if not (context.my_answer_md or "").strip():
        if result.cause_type != CauseType.UNKNOWN or result.error_step is not None:
            logger.info("mistake_analyze_unknown_answer forced=True")
        result.cause_type = CauseType.UNKNOWN
        result.secondary_causes = []
        result.error_step = None
        return result
    if result.error_step and not _quotes_student(result.error_step, context.my_answer_md or ""):
        logger.info("mistake_analyze_error_step_dropped reason=no_student_quote")
        result.error_step = None
    return result


def _quotes_student(error_step: str, my_answer: str) -> bool:
    """error_step 必须包含学生作答里的一个片段（≥2 字），否则视为泛泛而谈。"""
    text = my_answer.strip()
    if len(text) < 2:
        return False
    for size in range(min(12, len(text)), 1, -1):
        for start in range(0, len(text) - size + 1):
            if text[start : start + size] in error_step:
                return True
    return False