"""S4-1 单题结构化：一套 prompt + 一套 schema 覆盖单题与整卷兜底两种模式。

为什么统一返回数组：整卷兜底时一次要给多条；单题模式断言长度为 1 即可，
不需要维护第二套 prompt 与第二个 Pydantic 模型。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "question_extract_v1.md"
SCENE = "gen"
MAX_RETRIES = 2
_ANSWER_KEYS_LIMIT = 4


class QuestionExtractError(Exception):
    """抽取最终失败（含重试耗尽）；任务层据此计入 failed_items。"""


class ExtractedOption(BaseModel):
    key: str = Field(min_length=1, max_length=_ANSWER_KEYS_LIMIT)
    text: str = Field(min_length=1)


class ExtractedQuestion(BaseModel):
    stem_md: str
    options: list[ExtractedOption] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: Literal["单选", "多选", "填空", "解答"]
    difficulty: int = Field(ge=1, le=5)
    kp_names: list[str] = Field(default_factory=list)
    answer_source: Literal["paper", "ai", "none"] = "none"

    @model_validator(mode="after")
    def _validate_shape(self) -> "ExtractedQuestion":
        if len(self.stem_md.strip()) < 5:
            raise ValueError("题干过短")
        if self.qtype in {"单选", "多选"}:
            options = self.options or []
            if len(options) < 2:
                raise ValueError("选择题至少需要 2 个选项")
            keys = [option.key for option in options]
            if len(set(keys)) != len(keys):
                raise ValueError("选项 key 重复")
            answer = (self.answer_md or "").strip().upper().replace(" ", "")
            if answer:
                if any(char not in keys for char in answer):
                    raise ValueError("答案字母不在选项内")
                if self.qtype == "单选" and len(answer) != 1:
                    raise ValueError("单选题答案只能是 1 个字母")
                if len(set(answer)) != len(answer):
                    raise ValueError("多选题答案字母重复")
        elif self.options:
            raise ValueError("填空/解答题不应有选项")
        return self


class ExtractOutput(BaseModel):
    questions: list[ExtractedQuestion] = Field(default_factory=list)


@dataclass(frozen=True)
class ExtractResult:
    questions: list[ExtractedQuestion]
    truncated: bool = False


def render_prompt(
    *,
    mode: str,
    subject_name: str,
    section_qtype: str | None,
    expected_count: int | None,
    question_text: str,
) -> str:
    if not PROMPT_PATH.is_file():
        raise QuestionExtractError(f"Prompt 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(
            mode=mode,
            subject_name=subject_name,
            section_qtype=section_qtype,
            expected_count=expected_count,
            question_text=question_text,
        )
    except QuestionExtractError:
        raise
    except Exception as exc:
        raise QuestionExtractError(f"Prompt 渲染失败：{exc}") from exc


def extract_questions(
    *,
    question_text: str,
    mode: str = "single",
    subject_name: str = "高中数学",
    section_qtype: str | None = None,
    expected_count: int | None = None,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> ExtractResult:
    """单题 / 整卷兜底共用入口。

    整卷兜底（mode="block"）一次要吐 20 道题的 JSON，2048 token 必然截断成
    非法 JSON，重试也只是重复超限；所以预算按题数伸缩（每题约 400 token），
    并封顶 8192。单题模式维持 1500，不为一道题付整卷预算。
    """
    if not (question_text or "").strip():
        raise QuestionExtractError("题目文本为空")
    if mode not in {"single", "block"}:
        raise QuestionExtractError(f"未知模式：{mode}")
    client = llm_client or get_llm_client()
    prompt = render_prompt(
        mode=mode,
        subject_name=subject_name,
        section_qtype=section_qtype,
        expected_count=expected_count,
        question_text=question_text,
    )
    messages = [LLMMessage(role="user", content=prompt)]
    max_tokens = (
        1500 if mode == "single" else min(8192, max(2048, 400 * (expected_count or 1)))
    )
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        response = client.chat(messages, temperature=0.0, max_tokens=max_tokens, scene=SCENE)
        try:
            output = ExtractOutput.model_validate(loads_json_object(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            continue
        items = output.questions
        if not items:
            last_error = ValueError("模型未返回任何题目")
            continue
        if mode == "single":
            if len(items) != 1:
                last_error = ValueError(f"单题模式返回了 {len(items)} 条")
                continue
            return ExtractResult(questions=items)
        if expected_count is not None:
            if len(items) > expected_count:
                return ExtractResult(questions=items[:expected_count], truncated=True)
            return ExtractResult(questions=items)
        return ExtractResult(questions=items)
    raise QuestionExtractError(f"题目抽取失败（已重试 {max_retries} 次）：{last_error}")