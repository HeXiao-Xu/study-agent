"""S6-3 周笔记导图任务：LLM 聚类 + `weekly_mindmap` AgentTaskSpec。

聚类必须严格 JSON；失败重试 2 次后由任务定义降级为确定性结构树，不把
任务判失败。结果只写 `agent_tasks.result_json`，不新建笔记。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.gen.json_repair import loads_lenient_json
from app.ai.llm import LLMClient, LLMMessage, get_llm_client

logger = logging.getLogger(__name__)

PROMPT_VERSION = "weekly_mindmap_v1"
PROMPT_FILE = "weekly_mindmap_v1.md"
SCENE = "agent"
MAX_TOKENS = 2200
TEMPERATURE = 0.3
MAX_RETRIES = 2

_ENV = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[2] / "prompts")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


class ClusterError(Exception):
    """聚类重试耗尽：由任务定义捕获并降级。"""


class ClusterBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kp_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    conclusion: str = Field(min_length=1, max_length=200)
    note_ids: list[int] = Field(default_factory=list, max_length=20)
    children: list[str] = Field(default_factory=list, max_length=6)


class ClusterResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=60)
    branches: list[ClusterBranch] = Field(min_length=1, max_length=8)


@dataclass(frozen=True)
class ClusterContext:
    days: int
    notes: list[dict[str, Any]]
    subgraphs: list[dict[str, Any]]


def render_cluster_prompt(context: ClusterContext) -> str:
    return _ENV.get_template(PROMPT_FILE).render(
        days=context.days,
        notes_json=json.dumps(context.notes, ensure_ascii=False, indent=2),
        subgraphs_json=json.dumps(context.subgraphs, ensure_ascii=False, indent=2),
    )


def _valid_ids(context: ClusterContext) -> tuple[set[int], set[int]]:
    note_ids = {
        int(note["note_id"])
        for note in context.notes
        if note.get("note_id") is not None
    }
    kp_ids: set[int] = set()
    for subgraph in context.subgraphs:
        for node in subgraph.get("nodes") or []:
            if node.get("kp_id") is not None:
                kp_ids.add(int(node["kp_id"]))
    return note_ids, kp_ids


def _sanitize(result: ClusterResult, context: ClusterContext) -> ClusterResult:
    valid_notes, valid_kps = _valid_ids(context)
    branches: list[ClusterBranch] = []
    for branch in result.branches:
        note_ids = list(
            dict.fromkeys(int(note_id) for note_id in branch.note_ids if note_id in valid_notes)
        )
        kp_id = branch.kp_id if branch.kp_id in valid_kps else None
        children = [child.strip() for child in branch.children if child.strip()][:6]
        branches.append(
            ClusterBranch(
                kp_id=kp_id,
                title=branch.title.strip(),
                conclusion=branch.conclusion.strip(),
                note_ids=note_ids,
                children=children,
            )
        )
    return ClusterResult(title=result.title.strip(), branches=branches)


def generate_cluster(
    context: ClusterContext,
    *,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> tuple[ClusterResult, int]:
    """返回 (聚类结果, token 用量)；校验失败重试，耗尽抛 ClusterError。"""
    if max_retries < 0:
        raise ValueError("max_retries 不能为负")
    client = llm_client or get_llm_client()
    messages = [LLMMessage(role="user", content=render_cluster_prompt(context))]
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response = client.chat(
            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE
        )
        try:
            parsed = ClusterResult.model_validate(loads_lenient_json(response.text))
            cleaned = _sanitize(parsed, context)
            if not any(branch.note_ids for branch in cleaned.branches):
                raise ValueError("没有任何合法引用")
            return cleaned, int(response.total_tokens or 0)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.info("weekly_mindmap_cluster_retry attempt=%s error=%s", attempt + 1, exc)
    raise ClusterError(f"聚类失败（已尝试 {max_retries + 1} 次）：{last_error}")