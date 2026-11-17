"""S6-1 工具注册表：唯一登记点，顺序与方案 §6.7 一致。"""
from __future__ import annotations

from app.ai.agents.tools import (
    calculator,
    get_kp_subgraph,
    get_mastery,
    list_mistakes,
    list_notes,
    make_mindmap,
    search_notes,
    search_questions,
)

_TOOL_MODULES = (
    search_notes,
    list_notes,
    get_kp_subgraph,
    list_mistakes,
    get_mastery,
    search_questions,
    make_mindmap,
    calculator,
)

TOOL_ORDER: list[str] = [module.SPEC.name for module in _TOOL_MODULES]
TOOLS = {module.SPEC.name: module.SPEC for module in _TOOL_MODULES}