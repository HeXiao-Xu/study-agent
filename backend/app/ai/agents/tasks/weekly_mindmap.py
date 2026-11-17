"""S6-3 周笔记导图任务：LLM 聚类 + `weekly_mindmap` AgentTaskSpec。

聚类必须严格 JSON；失败重试 2 次后由任务定义降级为确定性结构树，不把
任务判失败。结果只写 `agent_tasks.result_json`，不新建笔记。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.agents.engine import PlanExtension
from app.ai.gen.json_repair import loads_lenient_json
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.core.exceptions import InvalidParamError

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

MAX_KPS = 3
LIST_LIMIT = 50


class WeeklyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=7, ge=1, le=30)
    subject_id: int | None = Field(default=None, ge=1)


class WeeklyMindmapTaskSpec:
    """过去 N 天笔记 → 知识点子图 → LLM 聚类 → Mermaid 导图。

    动态规划分三段：`list_notes` 后追加子图；子图后聚类并追加 `make_mindmap`；
    之后不再扩展。结果只写 `agent_tasks.result_json`。
    """

    task_type = "weekly_mindmap"

    def __init__(
        self,
        task_input: dict[str, Any],
        *,
        llm_client: LLMClient | None = None,
        now: datetime | None = None,
    ) -> None:
        self.task_input = task_input
        self.requires_confirm = False
        self._llm_client = llm_client
        self._now = now or datetime.now(timezone.utc)
        self._cluster: ClusterResult | None = None
        self._degraded = False

    @property
    def degraded(self) -> bool:
        return self._degraded

    @classmethod
    def validate_input(cls, raw: dict[str, Any]) -> dict[str, Any]:
        try:
            return WeeklyInput.model_validate(raw).model_dump()
        except ValidationError as exc:
            message = str(exc.errors()[0].get("msg", "任务输入不合法"))
            raise InvalidParamError(f"任务输入不合法：{message}") from exc

    # ------------------------------------------------------------- 规划
    def build_plan(self, state: Any) -> list[dict[str, Any]]:
        days = int(self.task_input.get("days") or 7)
        end = self._now.date()
        start = end - timedelta(days=days - 1)
        payload: dict[str, Any] = {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "limit": LIST_LIMIT,
        }
        if self.task_input.get("subject_id") is not None:
            payload["subject_id"] = int(self.task_input["subject_id"])
        return [
            {
                "tool": "list_notes",
                "input": payload,
                "purpose": f"取过去 {days} 天笔记",
            }
        ]

    def extend_plan(self, state: Any) -> PlanExtension:
        notes = self._notes(state)
        if not notes:
            return PlanExtension()
        planned = [str(step.get("tool")) for step in state.get("plan") or []]
        if "get_kp_subgraph" not in planned:
            kp_ids = self._top_kp_ids(notes)
            if kp_ids:
                return PlanExtension(
                    steps=[
                        {
                            "tool": "get_kp_subgraph",
                            "input": {"kp_id": kp_id, "depth": 1},
                            "purpose": f"取知识点 {kp_id} 的一跳关系",
                        }
                        for kp_id in kp_ids
                    ],
                    thought=f"按知识点追加 {len(kp_ids)} 个子图",
                )
        if "make_mindmap" not in planned:
            return self._mindmap_extension(notes, self._subgraphs(state))
        return PlanExtension()

    # ------------------------------------------------------------- 聚类
    def _mindmap_extension(
        self, notes: list[dict[str, Any]], subgraphs: list[dict[str, Any]]
    ) -> PlanExtension:
        days = int(self.task_input.get("days") or 7)
        context = ClusterContext(
            days=days,
            notes=[
                {
                    "note_id": note.get("note_id"),
                    "title": note.get("title"),
                    "preview": note.get("preview"),
                    "kp_names": note.get("kp_names") or [],
                }
                for note in notes
            ],
            subgraphs=subgraphs,
        )
        token_cost = 0
        try:
            cluster, token_cost = generate_cluster(
                context, llm_client=self._llm_client
            )
            self._cluster = cluster
            self._degraded = False
        except ClusterError:
            logger.info("weekly_mindmap_cluster_degraded")
            self._cluster = self._fallback_cluster(days, notes)
            self._degraded = True
        nodes = self._nodes_from_cluster(self._cluster)
        return PlanExtension(
            steps=[
                {
                    "tool": "make_mindmap",
                    "input": {"title": self._cluster.title, "nodes": nodes},
                    "purpose": "生成思维导图",
                }
            ],
            token_cost=token_cost,
            thought="聚类完成，追加导图生成",
        )

    def _fallback_cluster(
        self, days: int, notes: list[dict[str, Any]]
    ) -> ClusterResult:
        groups: dict[str, list[dict[str, Any]]] = {}
        for note in notes:
            names = note.get("kp_names") or []
            key = str(names[0]) if names else "学习笔记"
            groups.setdefault(key, []).append(note)
        branches: list[ClusterBranch] = []
        for name, items in groups.items():
            kp_ids = [int(kp_id) for item in items for kp_id in item.get("kp_ids") or []]
            branches.append(
                ClusterBranch(
                    kp_id=kp_ids[0] if kp_ids else None,
                    title=name[:200],
                    conclusion=f"本周记录了 {len(items)} 篇相关笔记",
                    note_ids=[
                        int(item["note_id"])
                        for item in items
                        if item.get("note_id") is not None
                    ],
                    children=[
                        str(item.get("title") or "")[:40] for item in items[:6]
                    ],
                )
            )
        return ClusterResult(title=f"过去 {days} 天学习导图"[:60], branches=branches)

    # ------------------------------------------------------------- 收尾
    def finalize(self, state: Any) -> dict[str, Any]:
        days = int(self.task_input.get("days") or 7)
        notes = self._notes(state)
        kp_count = len(
            {
                int(kp_id)
                for note in notes
                for kp_id in note.get("kp_ids") or []
            }
        )
        base: dict[str, Any] = {
            "task_type": self.task_type,
            "days": days,
            "note_count": len(notes),
            "kp_count": kp_count,
            "cluster_prompt_version": PROMPT_VERSION,
        }
        if not notes:
            return {
                **base,
                "summary_md": (
                    f"过去 {days} 天没有笔记，先记录一些学习内容再来生成导图。"
                ),
                "mermaid": "",
                "fallback_text": "",
                "citations": [],
                "degraded": False,
            }
        mindmap = self._mindmap_output(state)
        citations = self._citations(notes)
        summary = self._summary(notes)
        return {
            **base,
            "summary_md": summary,
            "mermaid": str(mindmap.get("mermaid") or ""),
            "fallback_text": str(mindmap.get("fallback_text") or ""),
            "citations": citations,
            "degraded": self._degraded,
        }

    # ------------------------------------------------------------- 工具
    @staticmethod
    def _notes(state: Any) -> list[dict[str, Any]]:
        for artifact in (state.get("artifacts") or {}).values():
            if artifact.get("tool") == "list_notes":
                items = (artifact.get("output") or {}).get("items") or []
                return list(items)
        return []

    @staticmethod
    def _subgraphs(state: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for artifact in (state.get("artifacts") or {}).values():
            if artifact.get("tool") != "get_kp_subgraph":
                continue
            output = artifact.get("output") or {}
            result.append(
                {
                    "nodes": output.get("nodes") or [],
                    "edges": output.get("edges") or [],
                }
            )
        return result

    @staticmethod
    def _top_kp_ids(notes: list[dict[str, Any]]) -> list[int]:
        counts: dict[int, int] = {}
        for note in notes:
            for kp_id in note.get("kp_ids") or []:
                counts[int(kp_id)] = counts.get(int(kp_id), 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [kp_id for kp_id, _ in ranked[:MAX_KPS]]

    @staticmethod
    def _nodes_from_cluster(cluster: ClusterResult) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for index, branch in enumerate(cluster.branches, start=1):
            branch_id = f"b{index}"
            nodes.append(
                {
                    "id": branch_id,
                    "name": branch.title[:80],
                    "parent_id": None,
                }
            )
            for child_index, child in enumerate(branch.children, start=1):
                nodes.append(
                    {
                        "id": f"{branch_id}_{child_index}",
                        "name": child[:40],
                        "parent_id": branch_id,
                    }
                )
        return nodes

    @staticmethod
    def _mindmap_output(state: Any) -> dict[str, Any]:
        for artifact in (state.get("artifacts") or {}).values():
            if artifact.get("tool") == "make_mindmap":
                return dict(artifact.get("output") or {})
        return {}

    def _summary(self, notes: list[dict[str, Any]]) -> str:
        days = int(self.task_input.get("days") or 7)
        lines = [f"## 过去 {days} 天学习摘要"]
        if self._cluster is None:
            lines.append("- 导图已生成，但本次任务没有保留聚类明细。")
            if self._degraded:
                lines.append("")
                lines.append("> LLM 聚类失败，已按知识点降级为结构树。")
            return "\n".join(lines)
        for branch in self._cluster.branches:
            suffix = ""
            if branch.note_ids:
                refs = "、".join(f"#{note_id}" for note_id in branch.note_ids)
                suffix = f"（引用：笔记 {refs}）"
            lines.append(f"- {branch.title}：{branch.conclusion}{suffix}")
        if self._degraded:
            lines.append("")
            lines.append("> LLM 聚类失败，已按知识点降级为结构树。")
        return "\n".join(lines)

    def _citations(self, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        titles = {
            int(note["note_id"]): str(note.get("title") or "")
            for note in notes
            if note.get("note_id") is not None
        }
        if self._cluster is None:
            return []
        seen: set[int] = set()
        citations: list[dict[str, Any]] = []
        for branch in self._cluster.branches:
            for note_id in branch.note_ids:
                if note_id in seen or note_id not in titles:
                    continue
                seen.add(note_id)
                citations.append(
                    {"note_id": note_id, "note_title": titles[note_id]}
                )
        return citations
