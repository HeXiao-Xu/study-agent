"""S2-10 LLM 候选内抽取：严格 JSON + Pydantic 校验 + 最多 2 次重试。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError

from app.ai.align.scoring import Candidate
from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "kp_align_v1.md"


class AlignError(Exception):
    """LLM 抽取最终失败；任务层据此重试/失败。"""


class AlignItem(BaseModel):
    kp_id: int
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(default="", max_length=200)


class AlignOutput(BaseModel):
    matches: list[AlignItem] = Field(default_factory=list)


@dataclass(frozen=True)
class LlmMatch:
    kp_id: int
    confidence: float
    evidence: str


def render_prompt(*, note_title: str, note_excerpt: str, candidates: list[Candidate]) -> str:
    if not PROMPT_PATH.is_file():
        raise AlignError(f"Prompt 模板不存在：{PROMPT_PATH}")
    env = Environment(
        loader=FileSystemLoader(str(PROMPT_PATH.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(PROMPT_PATH.name)
        return template.render(
            note_title=note_title, note_excerpt=note_excerpt, candidates=candidates
        )
    except Exception as exc:
        raise AlignError(f"Prompt 渲染失败：{exc}") from exc


def extract_matches(
    *,
    note_title: str,
    note_excerpt: str,
    candidates: list[Candidate],
    llm_client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[LlmMatch]:
    if not candidates:
        return []
    client = llm_client or get_llm_client()
    allowed = {c.kp_id for c in candidates}
    prompt = render_prompt(
        note_title=note_title, note_excerpt=note_excerpt, candidates=candidates
    )
    messages = [LLMMessage(role="user", content=prompt)]
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        response = client.chat(
            messages, temperature=0.0, max_tokens=800, scene="kp_align"
        )
        try:
            output = AlignOutput.model_validate(loads_json_object(response.text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            continue
        seen: set[int] = set()
        matches: list[LlmMatch] = []
        for item in output.matches:
            if item.kp_id not in allowed or item.kp_id in seen:
                continue
            seen.add(item.kp_id)
            matches.append(LlmMatch(item.kp_id, item.confidence, item.evidence))
        return matches
    raise AlignError(f"知识点抽取失败（已重试 {max_retries} 次）：{last_error}")