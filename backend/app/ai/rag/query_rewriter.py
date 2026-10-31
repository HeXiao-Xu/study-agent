"""S3-3 查询改写 LLM 层：Prompt + 严格 JSON + 最多 2 次重试。

错误信息只带类型/次数；Prompt、历史、模型输出正文一律不进异常。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rewrite_v1.md"
REWRITE_PROMPT_VERSION = "v1"

Intent = Literal["note_query", "question_query", "concept_explain", "chitchat"]

_CORRECTION = (
    "你上一次输出不是合法结果。请只输出一个 JSON 对象，字段为 "
    "intent/rewritten_query/is_followup/reply；非 chitchat 的 rewritten_query 必须非空，"
    "chitchat 的 reply 必须非空。"
)


class RewriteError(Exception):
    """改写最终失败；附带已发生的调用量，便于降级时如实记账。"""

    def __init__(
        self,
        message: str,
        *,
        llm_calls: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost_yuan: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.llm_calls = llm_calls
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cost_yuan = cost_yuan


@dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


class RewriteOutput(BaseModel):
    intent: Intent
    rewritten_query: str = Field(default="", max_length=500)
    is_followup: bool = False
    reply: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check_shape(self) -> "RewriteOutput":
        if self.intent != "chitchat" and not self.rewritten_query.strip():
            raise ValueError("非 chitchat 的 rewritten_query 不能为空")
        if self.intent == "chitchat" and not self.reply.strip():
            raise ValueError("chitchat 的 reply 不能为空")
        return self


@dataclass(frozen=True)
class RewriteCall:
    output: RewriteOutput
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_yuan: float
    latency_ms: int


def render_prompt(question: str, history: list[HistoryTurn]) -> str:
    if not PROMPT_PATH.is_file():
        raise RewriteError(f"Rewrite 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(history=history, question=question)
    except Exception as exc:
        raise RewriteError("Rewrite 模板渲染失败") from exc


def rewrite_with_llm(
    question: str,
    *,
    history: list[HistoryTurn] | None = None,
    llm_client: LLMClient | None = None,
    max_tokens: int = 400,
    max_retries: int = 2,
) -> RewriteCall:
    clean = question.strip()
    if not clean:
        raise ValueError("question 不能为空")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(clean, history or []))]
    started = time.perf_counter()
    llm_calls = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_yuan = 0.0
    last_error: Exception | None = None

    for _ in range(max_retries + 1):
        response = client.chat(
            messages,
            temperature=0.0,
            max_tokens=max_tokens,
            scene="query_rewrite",
        )
        llm_calls += 1
        prompt_tokens += response.prompt_tokens
        completion_tokens += response.completion_tokens
        total_tokens += response.total_tokens
        cost_yuan += response.cost_yuan
        try:
            output = RewriteOutput.model_validate(_loads_json(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages = messages + [
                LLMMessage(role="assistant", content=response.text),
                LLMMessage(role="user", content=_CORRECTION),
            ]
            continue
        return RewriteCall(
            output=output,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_yuan=cost_yuan,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    raise RewriteError(
        f"改写失败（已重试 {max_retries} 次）：{type(last_error).__name__}",
        llm_calls=llm_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_yuan=cost_yuan,
    )


def _loads_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean[3:]
        if clean[:4].lower() == "json":
            clean = clean[4:]
        if clean.endswith("```"):
            clean = clean[:-3]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(clean[start : end + 1])