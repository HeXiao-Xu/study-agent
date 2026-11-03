"""S4-5 迁移与模型契约：三列、两条 CHECK、scene 白名单。"""
from __future__ import annotations

from app.models.enums import EdgeReviewStatus, LLMCallScene, in_check
from app.models.knowledge_edge import KnowledgeEdge


def test_edge_has_review_columns():
    columns = set(KnowledgeEdge.__table__.columns.keys())
    assert {"review_status", "reviewed_by", "reviewed_at"} <= columns


def test_review_status_check_renders_all_three_values():
    assert in_check("review_status", EdgeReviewStatus) == (
        "review_status IN ('pending', 'approved', 'rejected')"
    )


def test_scene_whitelist_contains_graph():
    assert "graph" in [scene.value for scene in LLMCallScene]


def test_review_status_default_is_pending():
    column = KnowledgeEdge.__table__.columns["review_status"]
    assert column.server_default.arg == "pending"


def test_reviewed_by_fk_points_to_users():
    column = KnowledgeEdge.__table__.columns["reviewed_by"]
    targets = {fk.target_fullname for fk in column.foreign_keys}
    assert targets == {"users.id"}