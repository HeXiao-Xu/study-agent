"""S5-6 周报适配器：Prompt 渲染 → LLM → 数字校验 → 最多 2 次重试。"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.ai.llm import LLMClient, LLMError, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)

SCENE = "report"
PROMPT_VERSION = "weekly_report_v1"
PROMPT_FILE = "weekly_report_v1.md"
MAX_RETRIES = 2
MAX_TOKENS = 1400
TEMPERATURE = 0.3

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class WeeklyReportError(Exception):
    """LLM 失败、Prompt 渲染失败或数字校验重试耗尽。"""


@dataclass(frozen=True, slots=True)
class WeeklyReportContext:
    stats: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WeeklyReportResult:
    text: str
    attempts: int
    checked_numbers: list[str]
    invalid_numbers: list[str]


NumberValidator = Callable[[str], tuple[list[str], list[str]]]


def render_prompt(context: WeeklyReportContext) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(
            stats_json=json.dumps(
                context.stats, ensure_ascii=False, indent=2, sort_keys=True
            )
        )
    except Exception as exc:
        raise WeeklyReportError(f"prompt 渲染失败：{exc}") from exc


def generate_weekly_report(
    context: WeeklyReportContext,
    *,
    validator: NumberValidator,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> WeeklyReportResult:
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_prompt(context))]
    last_invalid: list[str] = []
    attempts = 0

    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        try:
            response = client.chat(
                messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                scene=SCENE,
            )
        except LLMError as exc:
            raise WeeklyReportError(f"LLM 调用失败（第 {attempts} 次）") from exc

        checked, invalid = validator(response.text)
        if response.text.strip() and checked and not invalid:
            return WeeklyReportResult(
                text=response.text.strip(),
                attempts=attempts,
                checked_numbers=checked,
                invalid_numbers=[],
            )
        last_invalid = invalid or ["<no-numbers>"]
        if attempt < max_retries:
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "以下数字不在输入中："
                        + "、".join(last_invalid)
                        + "；只能使用输入中出现的数字，重新输出完整周报。"
                    ),
                )
            )

    logger.warning("weekly_report_validation_failed attempts=%s", attempts)
    raise WeeklyReportError(
        f"周报数字校验失败（已尝试 {attempts} 次）：{last_invalid}"
    )