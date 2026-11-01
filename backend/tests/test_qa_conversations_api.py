"""S3-8 会话接口：TestClient + service monkeypatch，不连库。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.services import qa_service


class FakeSession:
    def __init__(self, user: User) -> None:
        self.user = user

    def scalar(self, statement: object):
        return self.user

    def get(self, entity: type, pk: int):
        raise AssertionError("unexpected get")


def _user(role: str = "student") -> User:
    user = User(
        username=f"s3_8_{role}",
        password_hash="hash",
        nickname="S3-8 测试用户",
        grade=None,
        role=role,
    )
    user.id = 7
    user.created_at = datetime.now(timezone.utc)
    return user


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _summary() -> qa_service.ConversationSummary:
    return qa_service.ConversationSummary(
        id=12,
        title="错位相减法",
        scope=None,
        created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        last_message_at=None,
        message_count=2,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_list_conversations_returns_string_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    monkeypatch.setattr(
        qa_service,
        "list_conversations",
        lambda session, **kwargs: [_summary()],
    )

    response = client.get(
        "/api/v1/qa/conversations", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data[0]["id"] == "12"
    assert data[0]["message_count"] == 2


def test_list_conversations_rejects_bad_limit(
    client: TestClient,
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    response = client.get(
        "/api/v1/qa/conversations?limit=0", headers=_headers(user)
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_conversation_messages_returns_detail(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    detail = qa_service.ConversationDetail(
        conversation=_summary(),
        messages=[
            qa_service.ConversationMessage(
                id=31,
                role="assistant",
                content_md="回答 [1]",
                created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                refused=False,
                citations=[
                    qa_service.ConversationCitation(
                        index=1,
                        note_id=55,
                        chunk_id=255,
                        title="数列笔记",
                        heading_path="数列/错位相减",
                        page_no=None,
                        snippet="片段",
                        score=0.9,
                        note_available=True,
                    )
                ],
            )
        ],
    )
    monkeypatch.setattr(
        qa_service,
        "get_conversation_detail",
        lambda session, **kwargs: detail,
    )

    response = client.get(
        "/api/v1/qa/conversations/12/messages", headers=_headers(user)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation"]["id"] == "12"
    assert data["messages"][0]["citations"][0]["index"] == 1


def test_conversation_messages_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "get_conversation_detail", missing)
    response = client.get(
        "/api/v1/qa/conversations/999/messages", headers=_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_conversations_require_student(client: TestClient) -> None:
    teacher = _user(role="teacher")
    app.dependency_overrides[get_db] = lambda: FakeSession(teacher)
    response = client.get(
        "/api/v1/qa/conversations", headers=_headers(teacher)
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_rename_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    monkeypatch.setattr(
        qa_service,
        "rename_conversation",
        lambda session, **kwargs: _summary(),
    )

    response = client.patch(
        "/api/v1/qa/conversations/12",
        headers=_headers(user),
        json={"title": "新标题"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == "12"


def test_rename_conversation_rejects_blank_title(client: TestClient) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    response = client.patch(
        "/api/v1/qa/conversations/12",
        headers=_headers(user),
        json={"title": "   "},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_delete_conversation_returns_204(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)
    called = {}
    monkeypatch.setattr(
        qa_service,
        "delete_conversation",
        lambda session, **kwargs: called.update(kwargs),
    )

    response = client.delete(
        "/api/v1/qa/conversations/12", headers=_headers(user)
    )

    assert response.status_code == 204
    assert called["conversation_id"] == 12


def test_delete_conversation_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user()
    app.dependency_overrides[get_db] = lambda: FakeSession(user)

    def missing(session, **kwargs):
        raise NotFoundError("会话不存在")

    monkeypatch.setattr(qa_service, "delete_conversation", missing)
    response = client.delete(
        "/api/v1/qa/conversations/999", headers=_headers(user)
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40400