"""S6-1 generate_questions：按知识点/难度生成题目草稿（不入库）。

复用 S4-4 的 `GeneratedVariant` 做字段与题型↔选项交叉校验，复用 lenient JSON
修复；生成结果只是草稿，是否入库由 S6-2 的人工确认流程决定。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, Field, ValidationError

from app.ai.agents.tools.base import (
    ToolContext,
    ToolExecutionError,
    ToolInput,
    ToolOutput,
    ToolSpec,
)
from app.ai.gen.json_repair import loads_lenient_json
from app.ai.gen.variant_generator import GeneratedVariant
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.core.exceptions import NotFoundError
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject

logger = logging.getLogger(__name__)

PROMPT_VERSION = "agent_gen_questions_v1"
PROMPT_FILE = "agent_gen_questions_v1.md"
SCENE = "gen"
MAX_TOKENS = 3500
TEMPERATURE = 0.7
MAX_RETRIES = 2
DIFFICULTY_LABELS = {1: "入门", 2: "简单", 3: "中等", 4: "较难", 5: "压轴"}

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class GenerationContext:
    kp_name: str
    subject_name: str
    difficulty: int
    qtype: str
    count: int


class GenerateQuestionsIn(ToolInput):
    kp_id: int = Field(ge=1)
    difficulty: int = Field(default=3, ge=1, le=5)
    count: int = Field(default=3, ge=1, le=5)
    qtype: Literal["单选", "多选", "填空", "解答"] = "解答"


class DraftOption(ToolOutput):
    key: str
    text: str


class QuestionDraft(ToolOutput):
    stem_md: str
    options: list[DraftOption] | None = None
    answer_md: str
    analysis_md: str
    qtype: str
    difficulty: int


class GenerateQuestionsOut(ToolOutput):
    kp_id: int
    kp_name: str
    difficulty: int
    qtype: str
    count: int
    questions: list[QuestionDraft]
    prompt_version: str
    attempts: int


class _ItemsOut(BaseModel):
    questions: list[GeneratedVariant]


def _question_shape(qtype: str) -> str:
    if qtype in ("单选", "多选"):
        return (
            "本题是选择题：options 必须给出至少 2 个选项，key 用 A/B/C/D 且唯一，"
            "所有选项的 text 都要具体；正确答案必须落在某个选项上。"
        )
    return "本题不是选择题：options 必须为 null，不要把选项写进题干。"


def render_prompt(context: GenerationContext) -> str:
    return _ENV.get_template(PROMPT_FILE).render(
        kp_name=context.kp_name,
        subject_name=context.subject_name,
        difficulty=context.difficulty,
        difficulty_label=DIFFICULTY_LABELS.get(context.difficulty, "中等"),
        qtype=context.qtype,
        count=context.count,
        question_shape=_question_shape(context.qtype),
    )


def generate_question_drafts(
    context: GenerationContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> tuple[list[GeneratedVariant], int]:
    """返回 (草稿列表, 实际调用次数)；条数/字段不合法都按失败重试。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response = client.chat(
            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE
        )
        try:
            parsed = _ItemsOut.model_validate(loads_lenient_json(response.text))
            if len(parsed.questions) != context.count:
                raise ValueError(
                    f"生成条数不符：{len(parsed.questions)} != {context.count}"
                )
            return parsed.questions, attempt + 1
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("agent_generate_questions_retry attempt=%s error=%s", attempt + 1, exc)
    raise ToolExecutionError("题目生成失败，请稍后重试") from last_error


def generate_questions(
    ctx: ToolContext,
    data: GenerateQuestionsIn,
    *,
    llm_client: LLMClient | None = None,
) -> GenerateQuestionsOut:
    kp = ctx.session.get(KnowledgePoint, data.kp_id)
    if kp is None:
        raise NotFoundError("知识点不存在")
    subject = ctx.session.get(Subject, kp.subject_id)
    subject_name = subject.name if subject is not None else "未知学科"
    context = GenerationContext(
        kp_name=kp.name,
        subject_name=subject_name,
        difficulty=data.difficulty,
        qtype=data.qtype,
        count=data.count,
    )
    try:
        drafts, attempts = generate_question_drafts(context, llm_client=llm_client)
    except ToolExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 - Prompt 渲染/未知异常统一固定话术
        logger.exception("agent_generate_questions_failed kp_id=%s", data.kp_id)
        raise ToolExecutionError("题目生成失败，请稍后重试") from exc
    return GenerateQuestionsOut(
        kp_id=data.kp_id,
        kp_name=kp.name,
        difficulty=data.difficulty,
        qtype=data.qtype,
        count=len(drafts),
        questions=[
            QuestionDraft(
                stem_md=draft.stem_md,
                options=(
                    [
                        DraftOption(key=option.key, text=option.text)
                        for option in draft.options
                    ]
                    if draft.options
                    else None
                ),
                answer_md=draft.answer_md,
                analysis_md=draft.analysis_md,
                qtype=draft.qtype,
                difficulty=draft.difficulty,
            )
            for draft in drafts
        ],
        prompt_version=PROMPT_VERSION,
        attempts=attempts,
    )


def _handler(ctx: ToolContext, data: GenerateQuestionsIn) -> GenerateQuestionsOut:
    return generate_questions(ctx, data)


SPEC = ToolSpec(
    name="generate_questions",
    description=(
        "用途：题库不足时按知识点与难度生成新题草稿；只返回候选，不入库，需人工确认后才可保存。"
        "参数 kp_id 指定知识点，difficulty 取 1–5，count 取 1–5，qtype 可选单选/多选/填空/解答。"
        "返回题目草稿（题干/选项/答案/解析/题型/难度）、Prompt 版本与实际调用次数。"
    ),
    input_model=GenerateQuestionsIn,
    output_model=GenerateQuestionsOut,
    handler=_handler,
)