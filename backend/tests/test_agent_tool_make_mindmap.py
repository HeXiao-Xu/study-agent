"""S6-1 make_mindmap：树/图两种 Mermaid 输出与纯文本降级。"""
from __future__ import annotations

from app.ai.agents.tools.make_mindmap import MindmapNode, build_mindmap


def _node(node_id: str, name: str, parent_id: str | None = None) -> MindmapNode:
    return MindmapNode(id=node_id, name=name, parent_id=parent_id)


def test_mindmap_builds_tree_from_parent_ids():
    out = build_mindmap(
        "上周函数",
        [_node("1", "函数"), _node("2", "定义域", "1"), _node("3", "值域", "1")],
        [],
    )
    assert out.mode == "mindmap"
    assert out.mermaid.splitlines()[0] == "mindmap"
    assert "root((上周函数))" in out.mermaid
    assert "定义域" in out.mermaid and "值域" in out.mermaid
    assert "- 函数" in out.fallback_text


def test_mindmap_falls_back_to_graph_on_cycle():
    nodes = [_node("a", "A", "b"), _node("b", "B", "a")]
    out = build_mindmap("环", nodes, [])
    assert out.mode == "graph"
    assert out.mermaid.startswith("graph TD")
    assert "A" in out.mermaid and "B" in out.mermaid


def test_mindmap_uses_edges_when_parent_missing():
    nodes = [MindmapNode(id="a", name="A"), MindmapNode(id="b", name="B")]
    out = build_mindmap("边", nodes, [{"src": "a", "dst": "b", "relation": "contains"}])
    assert out.mode == "mindmap"
    assert out.node_count == 2


def test_mindmap_sanitizes_labels_and_truncates():
    name = "函数(定义域)[值域]\n第二行" + "长" * 50
    out = build_mindmap("标题(测试)", [_node("1", name)], [])
    assert "\n第二行" not in out.mermaid
    assert "（" in out.mermaid  # 半角括号转全角，避免 Mermaid 语法冲突
    assert out.truncated is True
    assert out.node_count == 1


def test_mindmap_caps_nodes_at_80():
    nodes = [_node(str(i), f"节点{i}") for i in range(90)]
    out = build_mindmap("大图", nodes, [])
    assert out.node_count == 80
    assert out.truncated is True