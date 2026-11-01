"""S3-9 检索模式 schema：三配置、冲突、向后兼容。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.retrieval import RetrievalSearchRequest


@pytest.mark.parametrize("mode", ["vector", "hybrid", "hybrid_rerank"])
def test_accepts_three_retrieval_modes(mode: str) -> None:
    payload = RetrievalSearchRequest(query="函数", retrieval=mode)
    assert payload.retrieval == mode


@pytest.mark.parametrize(
    ("mode", "rerank"),
    [("vector", True), ("hybrid", True), ("hybrid_rerank", False)],
)
def test_rejects_conflicting_rerank(mode: str, rerank: bool) -> None:
    with pytest.raises(ValidationError, match="retrieval"):
        RetrievalSearchRequest(query="函数", retrieval=mode, rerank=rerank)


def test_rejects_unknown_retrieval_mode() -> None:
    with pytest.raises(ValidationError):
        RetrievalSearchRequest(query="函数", retrieval="magic")


def test_default_request_keeps_old_behavior() -> None:
    payload = RetrievalSearchRequest(query="函数")
    assert payload.retrieval is None
    assert payload.rerank is None