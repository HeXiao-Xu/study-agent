"""S3-4 Prompt 管理接口：TestClient + FakeSession/服务替身。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.prompt_template import PromptTemplate
from app.models.user import User
from app.services import prompt_service


class FakeSession:
    def __init__(self, *, user: User | None = None) -> None:
        self.user = user

    def scalar(self, statement: object):
        entity = statement.column_descriptions[0]["entity"]  # type: ignore[attr-defined]
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected entity: {entity}")


def _user(user_id: int = 1, *, role: str = "admin", username: str = "admin_1") -> User:
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


def _prompt(
    prompt_id: int, version: str, *, active: bool = False
) -> PromptTemplate:
    now = datetime.now(timezone.utc)
    prompt = PromptTemplate(
        name="qa",
        version=version,
        content="模板 {{ context }} {{ question }}",
        variables_json=["context", "question"],
        model_hint=None,
        is_active=active,
        created_by=1,
        created_at=now,
        updated_at=now,
    )
    prompt.id = prompt_id
    return prompt


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    app.dependency_overrides[get_db] = lambda: session


def test_list_prompts_requires_admin(client: TestClient) -> None:
    teacher = _user(2, role="teacher", username="teacher_1")
    _override(FakeSession(user=teacher))

    resp = client.get("/api/v1/admin/prompts", headers=_headers(teacher))

    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_list_prompts_requires_token(client: TestClient) -> None:
    _override(FakeSession())

    resp = client.get("/api/v1/admin/prompts")

    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_list_prompts_returns_history(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "list_prompts",
        lambda session, *, name: [_prompt(2, "v2"), _prompt(1, "v1", active=True)],
    )

    resp = client.get("/api/v1/admin/prompts?name=qa", headers=_headers(admin))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [item["version"] for item in data] == ["v2", "v1"]
    assert data[1]["is_active"] is True


def test_create_prompt_returns_201(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    captured: dict[str, object] = {}

    def fake_create(session, **kwargs):
        captured.update(kwargs)
        return _prompt(2, "v2", active=True)

    monkeypatch.setattr(prompt_service, "create_prompt_version", fake_create)

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={
            "name": "qa",
            "content": "模板 {{ context }} {{ question }}",
            "version": "v2",
            "variables_json": ["context", "question"],
            "activate": True,
        },
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["version"] == "v2"
    assert captured["created_by"] == admin.id
    assert captured["activate"] is True


def test_create_prompt_duplicate_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, **kwargs):
        raise ConflictError("Prompt 版本已存在")

    monkeypatch.setattr(prompt_service, "create_prompt_version", fail)

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={"name": "qa", "content": "模板", "version": "v1"},
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_create_prompt_invalid_body_returns_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "create_prompt_version",
        lambda session, **kwargs: pytest.fail("service 不应被调用"),
    )

    resp = client.post(
        "/api/v1/admin/prompts",
        headers=_headers(admin),
        json={"name": "qa", "content": "   "},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_activate_prompt_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))
    monkeypatch.setattr(
        prompt_service,
        "activate_prompt",
        lambda session, prompt_id: _prompt(prompt_id, "v2", active=True),
    )

    resp = client.put(
        "/api/v1/admin/prompts/2/activate", headers=_headers(admin)
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is True


def test_activate_prompt_unknown_returns_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _user()
    _override(FakeSession(user=admin))

    def fail(session, prompt_id):
        raise NotFoundError("Prompt 版本不存在")

    monkeypatch.setattr(prompt_service, "activate_prompt", fail)

    resp = client.put(
        "/api/v1/admin/prompts/99/activate", headers=_headers(admin)
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == 40400