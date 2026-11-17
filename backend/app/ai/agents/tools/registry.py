"""S6-1 工具注册表：唯一登记点，顺序与方案 §6.7 一致。"""
from __future__ import annotations

from app.ai.agents.tools import calculator, make_mindmap

_TOOL_MODULES = (
    make_mindmap,
    calculator,
)

TOOL_ORDER: list[str] = [module.SPEC.name for module in _TOOL_MODULES]
TOOLS = {module.SPEC.name: module.SPEC for module in _TOOL_MODULES}