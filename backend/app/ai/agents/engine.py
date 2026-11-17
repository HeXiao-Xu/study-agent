"""S6-2 LangGraph 状态机：plan → act → observe → reflect → confirm → finalize。

引擎只依赖注入的 `RunContext`（session/user/recorder/工具调用器），不 import
service 与 API，便于用 fake recorder 做纯单测。每个节点执行后由 recorder
落一条 `agent_steps`（与 `agent_tasks.state_json` 同事务）。
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.ai.agents.state import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_WAITING_CONFIRM,
    AgentState,
    PlanStep,
)
from app.ai.agents.tools import invoke_tool
from app.ai.agents.tools.base import ToolContext
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

MAX_TOOL_RETRIES = 2


class AgentStepLimitError(Exception):
    """步骤数达到上限；由 service 把任务置 failed。"""


class AgentTaskTimeoutError(Exception):
    """任务墙钟超时；由 service 把任务置 failed 并保留已有产物。"""


@dataclass(frozen=True)
class PlanExtension:
    """observe 成功后由任务定义追加的后续步骤（S6-3）。

    `token_cost` 是本次扩展（如 LLM 聚类）消耗的 token，由 observe 累加到任务。
    """

    steps: list[PlanStep] = field(default_factory=list)
    token_cost: int = 0
    thought: str | None = None


class StepRecorder(Protocol):
    def record(
        self,
        *,
        step_no: int,
        thought: str | None,
        status: str,
        state: AgentState,
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        tool_output: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None: ...


class AgentTaskSpec(Protocol):
    task_type: str
    requires_confirm: bool

    @classmethod
    def validate_input(cls, raw: dict[str, Any]) -> dict[str, Any]: ...

    def build_plan(self, state: AgentState) -> list[PlanStep]: ...

    def extend_plan(self, state: AgentState) -> PlanExtension: ...

    def finalize(self, state: AgentState) -> dict[str, Any]: ...


@dataclass
class RunContext:
    user: Any
    recorder: StepRecorder
    session: Any = None
    tool_invoker: Callable[[str, Any, dict[str, Any]], Any] = invoke_tool
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def invoke(self, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        context = ToolContext(session=self.session, user=self.user, now=self.now)
        output = self.tool_invoker(tool, context, payload)
        if isinstance(output, BaseModel):
            return output.model_dump(mode="json")
        return dict(output)


class AgentEngine:
    def __init__(self, spec: AgentTaskSpec, ctx: RunContext) -> None:
        self.spec = spec
        self.ctx = ctx

    # ------------------------------------------------------------------ 图
    def run(self, state: AgentState) -> AgentState:
        return self._build_graph().invoke(state)

    def _build_graph(self):  # noqa: ANN202 - 动态组装，返回 CompiledStateGraph
        builder = StateGraph(AgentState)
        builder.add_node("plan", self._guard(self._plan))
        builder.add_node("act", self._guard(self._act))
        builder.add_node("observe", self._guard(self._observe))
        builder.add_node("reflect", self._guard(self._reflect))
        builder.add_node("confirm", self._guard(self._confirm))
        builder.add_node("finalize", self._guard(self._finalize))
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_plan,
            {"act": "act", "confirm": "confirm", "finalize": "finalize"},
        )
        builder.add_edge("act", "observe")
        builder.add_conditional_edges(
            "observe",
            self._route_observe,
            {"act": "act", "reflect": "reflect", "confirm": "confirm", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "reflect", self._route_reflect, {"act": "act", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "confirm", self._route_confirm, {"finalize": "finalize", "end": END}
        )
        builder.add_edge("finalize", END)
        return builder.compile()

    def _guard(self, node: Callable[[AgentState], dict[str, Any]]):  # noqa: ANN201
        def wrapped(state: AgentState) -> dict[str, Any]:
            deadline = state.get("deadline_at")
            if deadline is not None and time.time() > float(deadline):
                logger.warning(
                    "agent_task_timeout task_id=%s deadline=%s",
                    state.get("user_id"),
                    deadline,
                )
                raise AgentTaskTimeoutError("任务执行超时")
            max_steps = int(state.get("max_steps") or 0)
            if int(state.get("step_count") or 0) >= max_steps:
                logger.warning(
                    "agent_step_limit task_id=%s step_count=%s max_steps=%s",
                    state.get("user_id"),
                    state.get("step_count"),
                    max_steps,
                )
                raise AgentStepLimitError(f"超过最大步数 {max_steps}")
            return node(state)

        return wrapped

    def _record(
        self,
        state: AgentState,
        update: dict[str, Any],
        *,
        thought: str | None,
        status: str,
        tool_name: str | None = None,
        tool_input: dict[str, Any] | None = None,
        tool_output: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        merged = {**state, **update}
        step_no = int(state.get("step_count") or 0) + 1
        merged["step_count"] = step_no
        update["step_count"] = step_no
        self.ctx.recorder.record(
            step_no=step_no,
            thought=thought,
            status=status,
            state=merged,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            latency_ms=latency_ms,
        )

    def _budget_hit(self, state: AgentState, update: dict[str, Any]) -> bool:
        budget = int(state.get("token_budget") or 0)
        cost = int(update.get("token_cost", state.get("token_cost") or 0))
        if budget > 0 and cost >= budget:
            logger.warning(
                "agent_budget_exhausted task_id=%s cost=%s budget=%s",
                state.get("user_id"),
                cost,
                budget,
            )
            update["fatal_error"] = "token 预算不足，已终止并保留现有产物"
            return True
        return False

    # ---------------------------------------------------------------- 节点
    def _plan(self, state: AgentState) -> dict[str, Any]:
        if state.get("resume_from"):
            return {}
        plan = list(self.spec.build_plan(state))
        update: dict[str, Any] = {
            "plan": plan,
            "current_index": 0,
            "status": STATUS_RUNNING,
        }
        hit = self._budget_hit(state, update)
        tools = "、".join(step["tool"] for step in plan)
        self._record(
            state,
            update,
            thought=f"计划 {len(plan)} 步：{tools}",
            status="error" if hit else "ok",
        )
        return update

    def _act(self, state: AgentState) -> dict[str, Any]:
        plan = state.get("plan") or []
        index = int(state.get("current_index") or 0)
        step = plan[index]
        tool = str(step["tool"])
        started = time.perf_counter()
        try:
            output = self.ctx.invoke(tool, dict(step.get("input") or {}))
        except AppError as exc:
            logger.warning(
                "agent_tool_failed tool=%s step_no=%s code=%s error=%s",
                tool,
                index + 1,
                exc.code,
                exc.message,
            )
            latency = int(round((time.perf_counter() - started) * 1000))
            update = {"last_error": exc.message, "last_output": None}
            self._record(
                state,
                update,
                thought=f"工具 {tool} 失败：{exc.message}",
                status="error",
                tool_name=tool,
                tool_input=dict(step.get("input") or {}),
                tool_output={"error": exc.message, "code": exc.code},
                latency_ms=latency,
            )
            return update
        except TimeoutError:
            logger.warning(
                "agent_tool_timeout tool=%s step_no=%s", tool, index + 1
            )
            latency = int(round((time.perf_counter() - started) * 1000))
            message = "工具执行超时"
            update = {"last_error": message, "last_output": None}
            self._record(
                state,
                update,
                thought=f"工具 {tool} 超时：{message}",
                status="error",
                tool_name=tool,
                tool_input=dict(step.get("input") or {}),
                tool_output={"error": message, "code": 50000},
                latency_ms=latency,
            )
            return update
        except Exception:  # noqa: BLE001 - 未预期异常也走重试，堆栈只进日志
            logger.exception("agent_tool_failed tool=%s", tool)
            latency = int(round((time.perf_counter() - started) * 1000))
            message = "工具执行失败"
            update = {"last_error": message, "last_output": None}
            self._record(
                state,
                update,
                thought=f"工具 {tool} 失败：{message}",
                status="error",
                tool_name=tool,
                tool_input=dict(step.get("input") or {}),
                tool_output={"error": message, "code": 50000},
                latency_ms=latency,
            )
            return update
        latency = int(round((time.perf_counter() - started) * 1000))
        update = {"last_error": None, "last_output": output}
        self._record(
            state,
            update,
            thought=str(step.get("purpose") or f"调用 {tool}"),
            status="ok",
            tool_name=tool,
            tool_input=dict(step.get("input") or {}),
            tool_output=output,
            latency_ms=latency,
        )
        return update

    def _observe(self, state: AgentState) -> dict[str, Any]:
        plan = state.get("plan") or []
        index = int(state.get("current_index") or 0)
        tool = str(plan[index]["tool"]) if index < len(plan) else "unknown"
        if state.get("last_error"):
            update: dict[str, Any] = {}
            self._record(
                state,
                update,
                thought=f"步骤 {index + 1} 失败，准备重试或终止",
                status="error",
            )
            return update
        output = state.get("last_output") or {}
        artifacts = dict(state.get("artifacts") or {})
        artifacts[f"step_{index + 1}"] = {
            "tool": tool,
            "input": dict(plan[index].get("input") or {}),
            "output": output,
        }
        citations = list(state.get("citations") or [])
        if tool == "search_notes":
            for hit in output.get("hits") or []:
                citations.append(
                    {
                        "note_id": hit.get("note_id"),
                        "note_title": hit.get("note_title"),
                        "chunk_id": hit.get("chunk_id"),
                    }
                )
        update: dict[str, Any] = {
            "artifacts": artifacts,
            "citations": citations,
            "current_index": index + 1,
            "last_output": None,
            "last_error": None,
            "retry_count": 0,
        }
        prospective = {**state, **update}
        extension = self.spec.extend_plan(prospective)
        if extension.steps:
            plan.extend(extension.steps)
            update["plan"] = list(plan)
            prospective["plan"] = update["plan"]
        if extension.token_cost:
            update["token_cost"] = (
                int(prospective.get("token_cost") or 0) + extension.token_cost
            )
            prospective["token_cost"] = update["token_cost"]
        hit = self._budget_hit(prospective, update)
        self._record(
            state,
            update,
            thought=extension.thought or f"步骤 {index + 1} 成功，产物已收集",
            status="error" if hit else "ok",
        )
        return update

    def _reflect(self, state: AgentState) -> dict[str, Any]:
        retries = int(state.get("retry_count") or 0)
        if retries >= MAX_TOOL_RETRIES:
            logger.warning(
                "agent_tool_retry_exhausted tool=%s step_no=%s error=%s",
                (state.get("plan") or [{}])[int(state.get("current_index") or 0)].get("tool")
                if (state.get("plan") or [])
                else None,
                int(state.get("current_index") or 0) + 1,
                state.get("last_error"),
            )
            update = {
                "fatal_error": f"工具连续失败已达重试上限：{state.get('last_error')}"
            }
            self._record(state, update, thought="重试次数用尽，终止任务", status="error")
            return update
        logger.warning(
            "agent_tool_retry tool=%s step_no=%s retry=%s",
            (state.get("plan") or [{}])[int(state.get("current_index") or 0)].get("tool")
            if (state.get("plan") or [])
            else None,
            int(state.get("current_index") or 0) + 1,
            retries + 1,
        )
        update = {"retry_count": retries + 1, "last_error": None}
        self._record(
            state,
            update,
            thought=f"工具失败，第 {retries + 1} 次重试",
            status="ok",
        )
        return update

    def _confirm(self, state: AgentState) -> dict[str, Any]:
        decision = state.get("confirm_decision")
        if not decision:
            update = {"need_human_confirm": True, "status": STATUS_WAITING_CONFIRM}
            self._record(state, update, thought="等待人工确认", status="waiting_confirm")
            return update
        comment = decision.get("comment")
        if decision.get("approved"):
            update = {
                "need_human_confirm": False,
                "status": STATUS_RUNNING,
                "resume_from": None,
            }
            thought = "人工确认通过" + (f"：{comment}" if comment else "")
            self._record(state, update, thought=thought, status="ok")
            return update
        update = {
            "need_human_confirm": False,
            "status": STATUS_FAILED,
            "resume_from": None,
            "fatal_error": "用户拒绝确认",
        }
        thought = "人工拒绝确认" + (f"：{comment}" if comment else "")
        self._record(state, update, thought=thought, status="error")
        return update

    def _finalize(self, state: AgentState) -> dict[str, Any]:
        fatal = state.get("fatal_error")
        if state.get("status") == STATUS_FAILED or fatal:
            error = fatal or "任务执行失败"
            result = {
                "artifacts": state.get("artifacts") or {},
                "citations": state.get("citations") or [],
            }
            update = {"status": STATUS_FAILED, "error": error, "result": result}
            self._record(state, update, thought=f"任务失败：{error}", status="error")
            return update
        try:
            result = self.spec.finalize(state)
        except Exception:  # noqa: BLE001 - 收尾失败按任务失败处理，堆栈进日志
            logger.exception("agent_finalize_failed")
            update = {
                "status": STATUS_FAILED,
                "error": "任务收尾失败",
                "result": {
                    "artifacts": state.get("artifacts") or {},
                    "citations": state.get("citations") or [],
                },
            }
            self._record(state, update, thought="任务失败：收尾失败", status="error")
            return update
        update = {"status": STATUS_SUCCEEDED, "result": result, "error": None}
        self._record(state, update, thought="任务完成", status="ok")
        return update

    # ---------------------------------------------------------------- 路由
    def _route_plan(self, state: AgentState) -> str:
        if state.get("resume_from") == "confirm":
            return "confirm"
        if state.get("fatal_error"):
            return "finalize"
        if state.get("resume_from") == "resume":
            if int(state.get("current_index") or 0) < len(state.get("plan") or []):
                return "act"
            return "confirm" if self.spec.requires_confirm else "finalize"
        if not state.get("plan"):
            return "finalize"
        return "act"

    def _route_observe(self, state: AgentState) -> str:
        if state.get("last_error"):
            return "reflect"
        if state.get("fatal_error"):
            return "finalize"
        if int(state.get("current_index") or 0) >= len(state.get("plan") or []):
            return "confirm" if self.spec.requires_confirm else "finalize"
        return "act"

    def _route_reflect(self, state: AgentState) -> str:
        return "finalize" if state.get("fatal_error") else "act"

    def _route_confirm(self, state: AgentState) -> str:
        return "end" if state.get("confirm_decision") is None else "finalize"