"""S5-2 组卷接口：权限、状态码、出参字段与归属隔离。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.paper import Paper
from app.models.user import User

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _user(role: str = "student", user_id: int = 50) -> User:
    user = User(
        username=f"{role}_s52", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = user_id
    return user


class FakeSession:
    """feed 顺序与 service 的查询顺序一致；scalar 只服务 get_current_user。"""

    def __init__(self, *, results=None, paper=None, user=None) -> None:
        self.results = [list(rows) for rows in (results or [])]
        self.paper = paper
        self.user = user
        self.added: list[object] = []
        self.committed = 0

    def execute(self, statement):  # noqa: ANN001, ANN201
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user if "users" in str(statement) else None

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper is not None and self.paper.id == pk else None
        return None

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        obj.id = 7
        obj.created_at = NOW


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session: FakeSession, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _payload(**overrides):  # noqa: ANN003, ANN202
    data = {
        "kp_ids": [101],
        "total_questions": 2,
        "qtype_ratio": {"单选": 1.0},
        "difficulty_dist": {"2": 1.0},
        "total_score": 6,
        "seed": 7,
    }
    data.update(overrides)
    return data


def _candidate_rows():  # noqa: ANN202
    return [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (502, "单选", 2, False, "upload", 101, Decimal("0.800000")),
        (503, "解答", 3, True, "textbook", 101, Decimal("1.000000")),
    ]


def _detail_rows():  # noqa: ANN202
    return [
        (501, 7, "单选", 2, "题干 501", [{"key": "A", "text": "选项 A"}], "答案 501", None, True, "exam"),
        (502, 7, "单选", 2, "题干 502", [], "答案 502", None, False, "upload"),
        (503, 7, "解答", 3, "题干 503", [], "答案 503", None, True, "textbook"),
    ]


def _generate_results():  # noqa: ANN202
    return [_candidate_rows(), [], [], _detail_rows()]


def _stored_paper() -> Paper:
    paper = Paper(
        user_id=50,
        title="期中卷",
        constraint_json={"seed": 7},
        question_ids=[501, 502],
        total_score=11,
        duration_min=60,
        status="草稿",
        generated_by="manual",
    )
    paper.id = 7
    paper.created_at = NOW
    return paper


def test_generate_requires_login():
    client = TestClient(app)
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_generate_forbids_teacher():
    client = _client(FakeSession(user=_user("teacher", 9)), _user("teacher", 9))
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_generate_returns_preview_with_items():
    student = _user()
    client = _client(FakeSession(results=_generate_results(), user=student), student)
    response = client.post("/api/v1/papers/generate", json=_payload())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ok"] is True
    assert data["seed"] == 7
    assert data["constraint"]["score_by_qtype"] == {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
    assert len(data["items"]) == 2
    assert data["items"][0]["stem_md"].startswith("题干")
    assert data["items"][0]["parts"]["total"] > 0


def test_generate_rejects_empty_kp_ids():
    student = _user()
    client = _client(FakeSession(user=student), student)
    response = client.post("/api/v1/papers/generate", json=_payload(kp_ids=[]))
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_replace_item_returns_new_item():
    student = _user()
    rows = _candidate_rows()
    session = FakeSession(results=[rows, [], [], _detail_rows()], user=student)
    client = _client(session, student)
    body = _payload(
        selected_question_ids=[501, 502, 503], replace_question_id=501
    )
    response = client.post("/api/v1/papers/replace-item", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["replaced"] is False
    assert data["reason"] == "没有可替换的候选题"


def test_replace_item_replaces_when_candidate_available():
    student = _user()
    rows = _candidate_rows() + [(504, "单选", 2, True, "mock", 101, Decimal("1.000000"))]
    details = [(504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock")]
    session = FakeSession(results=[rows, [], [], details], user=student)
    client = _client(session, student)
    body = _payload(selected_question_ids=[501], replace_question_id=501)
    response = client.post("/api/v1/papers/replace-item", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["replaced"] is True
    assert data["item"]["question_id"] == 504


def test_save_paper_returns_201_with_recomputed_score():
    student = _user()
    session = FakeSession(results=[[(501, "单选"), (502, "解答")]], user=student)
    client = _client(session, student)
    body = {"title": "期中卷", "constraint": _payload(total_score=11), "question_ids": [501, 502]}
    response = client.post("/api/v1/papers", json=body)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["id"] == 7
    assert data["total_score"] == 11
    assert data["status"] == "草稿"
    assert data["question_ids"] == [501, 502]


def test_save_paper_rejects_missing_question():
    student = _user()
    session = FakeSession(results=[[(501, "单选")]], user=student)
    client = _client(session, student)
    body = {"title": "t", "constraint": _payload(), "question_ids": [501, 999]}
    response = client.post("/api/v1/papers", json=body)
    assert response.status_code == 422
    assert "999" in response.json()["message"]


def test_get_paper_returns_items_and_missing_ids():
    student = _user()
    session = FakeSession(
        results=[
            [(501, 7, "单选", 2, "题干 501", [], "答案 501", None, True, "exam")],
            [(501, 101)],
        ],
        paper=_stored_paper(),
        user=student,
    )
    client = _client(session, student)
    response = client.get("/api/v1/papers/7")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 7
    assert data["items"][0]["question_id"] == 501
    assert data["missing_question_ids"] == [502]


def test_get_paper_forbids_other_user():
    other = _user("student", 51)  # token 与回表用户都是 51，而 paper 属于 50
    session = FakeSession(paper=_stored_paper(), user=other)
    client = _client(session, other)
    response = client.get("/api/v1/papers/7")
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_get_paper_returns_404_for_missing_id():
    student = _user()
    session = FakeSession(paper=None, user=student)
    client = _client(session, student)
    response = client.get("/api/v1/papers/999")
    assert response.status_code == 404
    assert response.json()["code"] == 40400