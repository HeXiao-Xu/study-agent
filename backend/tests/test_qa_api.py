"""S3-5 QA 接口：TestClient + 依赖覆盖，不触库、不调外部 LLM。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.message_citation import MessageCitation
from app.models.user import User
from app.services import qa_service


class FakeSession:
    def __init__(self, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        from app.models.user import User as UserModel

        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is UserModel:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")

    def get(self, entity: type, pk: int):
        raise AssertionError(f"unexpected get: {entity}")


def _user(user_id: int = 1, *, role: str = "student", username: str = "student_1") -> User:
    user = User(
        username=username,
        password_hash="hash",
        nickname=f"测试用户_{user_id}",
        grade=None,
        role=role,
    )
    user.id = user_id
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _plan() -> qa_service.QaPlan:
    return qa_service.QaPlan(
        user_id=1,
        conversation_id=12,
        user_message_id=30,
        question="问题",
        kind="chitchat",
        prepared=None,
        chitchat_reply="你好",
        citations=[],
        prompt_version=None,
        rewrite=None,
        started_at=0.0,
    )


def _override_user(user: User) -> None:
    app.dependency_overrides[get_db] = lambda: FakeSession(user)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(
        qa_service,
        "prepare_ask",
        lambda session, **kwargs: _plan(),
    )
    monkeypatch.setattr(
        qa_service,
        "stream_events",
        lambda plan, **kwargs: iter(
            [
                qa_service.QaStreamEvent(
                    event="meta",
                    data={
                        "conversation_id": "12",
                        "user_message_id": 30,
                        "citations": [],
                    },
                ),
                qa_service.QaStreamEvent(event="delta", data={"text": "你好"}),
                qa_service.QaStreamEvent(
                    event="done",
                    data={
                        "message_id": 31,
                        "conversation_id": "12",
                        "tokens": 15,
                        "latency_ms": 20,
                        "refused": False,
                        "refusal_reason": None,
                        "suggestions": [],
                    },
                ),
            ]
        ),
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_qa_ask_streams_sse_frames(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    with client.stream(
        "POST",
        "/api/v1/qa/ask",
        headers=_headers(user),
        json={"question": "你好"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())

    assert "event: meta" in body
    assert '"conversation_id":"12"' in body
    assert "event: delta" in body
    assert '"text":"你好"' in body
    assert "event: done" in body
    assert '"refusal_reason":null' in body
    assert '"suggestions":[]' in body
    assert body.endswith("\n\n")


def test_qa_done_contract_supports_refusal_suggestions() -> None:
    from app.schemas.qa import QaDoneData, QaSuggestion

    data = QaDoneData(
        message_id=31,
        conversation_id="12",
        tokens=15,
        latency_ms=20,
        refused=True,
        refusal_reason="no_valid_citation",
        suggestions=[
            QaSuggestion(type="rephrase", text="换问法"),
            QaSuggestion(type="note", text="补笔记"),
        ],
    )
    assert data.suggestions[0].type == "rephrase"
    assert data.refusal_reason == "no_valid_citation"


def test_qa_done_contract_rejects_unknown_suggestion_type() -> None:
    from app.schemas.qa import QaDoneData

    with pytest.raises(ValidationError):
        QaDoneData(
            message_id=31,
            conversation_id="12",
            tokens=15,
            latency_ms=20,
            refused=True,
            suggestions=[{"type": "other", "text": "未知建议"}],
        )


def test_qa_ask_requires_student(client: TestClient) -> None:
    teacher = _user(role="teacher", username="teacher_1")
    _override_user(teacher)
    response = client.post(
        "/api/v1/qa/ask",
        headers=_headers(teacher),
        json={"question": "问题"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_qa_ask_rejects_bad_request(client: TestClient) -> None:
    user = _user()
    _override_user(user)
    for payload in (
        {"question": "  "},
        {"question": "问题", "conversation_id": "abc"},
        {"question": "问题", "scope": {"chunk_types": ["note"]}},
    ):
        response = client.post(
            "/api/v1/qa/ask", headers=_headers(user), json=payload
        )
        assert response.status_code == 422
        assert response.json()["code"] == 42200


def test_qa_ask_returns_404_for_missing_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "prepare_ask", missing)
    response = client.post(
        "/api/v1/qa/ask",
        headers=_headers(user),
        json={"question": "问题", "conversation_id": "999"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_get_message_citations_returns_own_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)
    row = MessageCitation(
        message_id=31,
        chunk_id=101,
        note_id=55,
        score=0.9,
        snippet="正文",
        page_no=2,
        rank=1,
    )
    row.id = 99
    monkeypatch.setattr(
        qa_service,
        "get_message_citations",
        lambda session, **kwargs: [row],
    )

    response = client.get(
        "/api/v1/qa/messages/31/citations", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == 99
    assert data[0]["chunk_id"] == 101
    assert data[0]["rank"] == 1


def test_get_message_citations_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    _override_user(user)

    def missing(session, **kwargs):
        raise NotFoundError("消息不存在")

    monkeypatch.setattr(qa_service, "get_message_citations", missing)
    response = client.get(
        "/api/v1/qa/messages/999/citations", headers=_headers(user)
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40400