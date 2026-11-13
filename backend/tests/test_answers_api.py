"""S5-4 作答接口：权限、入参校验、错误码与出参字段。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import papers as papers_api
from app.core.security import create_access_token
from app.main import app
from app.models.answer import Answer
from app.models.user import User
from app.schemas.answer import (
    AnswerRowOut,
    GradedItemOut,
    MasteryDeltaOut,
    PaperAnswersOut,
    PaperBriefOut,
    PaperSubmitOut,
)

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _user(role: str = "student", user_id: int = 50) -> User:
    user = User(
        username=f"{role}_s54", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = user_id
    return user


class FakeAuthSession:
    """只服务 get_current_user 的回表；业务 service 已被 monkeypatch。"""

    def __init__(self, user: User) -> None:
        self.user = user

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.user if model is User else None

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _client(user: User | None = None, *, token: bool = True) -> TestClient:
    app.dependency_overrides[deps.get_db] = lambda: FakeAuthSession(user or _user())
    client = TestClient(app)
    if token:
        user = user or _user()
        client.headers.update(
            {"Authorization": f"Bearer {create_access_token(user_id=user.id, role=user.role).token}"}
        )
    return client


def _row(question_id: int = 501, *, saved: bool = True) -> AnswerRowOut:
    return AnswerRowOut(
        question_id=question_id,
        user_answer_md="A",
        self_rated=1.0,
        is_correct=True,
        score=3.0,
        time_spent_sec=12,
        saved=saved,
    )


def _answers_out() -> PaperAnswersOut:
    return PaperAnswersOut(
        paper=PaperBriefOut(id=8, title="验收卷", status="已生成", total_score=11),
        items=[_row(501), _row(502, saved=False)],
        submitted=False,
        earned_score=3.0,
    )


def _submit_out() -> PaperSubmitOut:
    return PaperSubmitOut(
        paper_id=8,
        score=7.0,
        total_score=11,
        correct_count=2,
        question_count=2,
        elapsed_sec=30,
        items=[
            GradedItemOut(
                question_id=501,
                qtype="单选",
                is_correct=True,
                score=3.0,
                self_rated=1.0,
                user_answer_md="A",
            )
        ],
        mastery=[
            MasteryDeltaOut(
                kp_id=117,
                kp_name="函数",
                mastery_before=None,
                mastery_after=0.117,
                attempts_delta=1,
            )
        ],
        mistake_question_ids=[502],
        missing_question_ids=[],
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_get_answers_returns_envelope(monkeypatch):
    monkeypatch.setattr(
        papers_api.answer_service,
        "get_answers",
        lambda session, **kwargs: _answers_out(),
    )
    resp = _client().get("/api/v1/papers/8/answers")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["submitted"] is False
    assert data["earned_score"] == 3.0
    assert [row["question_id"] for row in data["items"]] == [501, 502]
    assert data["items"][1]["saved"] is False


def test_get_answers_allows_generated_and_submitted_statuses(monkeypatch):
    out = _answers_out()
    out.paper.status = "已提交"
    out.submitted = True
    monkeypatch.setattr(
        papers_api.answer_service, "get_answers", lambda session, **kwargs: out
    )
    resp = _client().get("/api/v1/papers/8/answers")
    assert resp.status_code == 200
    assert resp.json()["data"]["submitted"] is True


def test_get_answers_requires_login():
    resp = _client(token=False).get("/api/v1/papers/8/answers")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


def test_get_answers_requires_student_role():
    resp = _client(_user("teacher")).get("/api/v1/papers/8/answers")
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_get_answers_propagates_forbidden(monkeypatch):
    from app.core.exceptions import ForbiddenError

    def boom(session, **kwargs):
        raise ForbiddenError("无权访问该试卷")

    monkeypatch.setattr(papers_api.answer_service, "get_answers", boom)
    resp = _client().get("/api/v1/papers/8/answers")
    assert resp.status_code == 403
    assert resp.json()["message"] == "无权访问该试卷"


def test_save_answer_returns_saved_row(monkeypatch):
    captured: dict = {}

    def fake_save(session, **kwargs):
        captured.update(kwargs)
        return AnswerRowOut(
            question_id=501,
            user_answer_md="A",
            self_rated=None,
            is_correct=None,
            score=None,
            time_spent_sec=12,
            saved=True,
        )

    monkeypatch.setattr(papers_api.answer_service, "save_answer", fake_save)
    resp = _client().put(
        "/api/v1/papers/8/answers/501",
        json={"user_answer_md": "A", "time_spent_sec": 12},
    )
    assert resp.status_code == 200
    assert captured["paper_id"] == 8
    assert captured["question_id"] == 501
    assert captured["user_id"] == 50
    assert resp.json()["data"]["saved"] is True


def test_save_answer_rejects_negative_time():
    resp = _client().put(
        "/api/v1/papers/8/answers/501",
        json={"user_answer_md": "A", "time_spent_sec": -1},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_save_answer_rejects_overlong_answer():
    resp = _client().put(
        "/api/v1/papers/8/answers/501",
        json={"user_answer_md": "x" * 20001},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_save_answer_rejects_submitted_paper(monkeypatch):
    from app.core.exceptions import ConflictError

    def boom(session, **kwargs):
        raise ConflictError("试卷已提交，不能再修改答案")

    monkeypatch.setattr(papers_api.answer_service, "save_answer", boom)
    resp = _client().put("/api/v1/papers/8/answers/501", json={"user_answer_md": "A"})
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900
    assert resp.json()["message"] == "试卷已提交，不能再修改答案"


def test_submit_paper_returns_summary(monkeypatch):
    captured: dict = {}

    def fake_submit(session, **kwargs):
        captured.update(kwargs)
        return _submit_out()

    monkeypatch.setattr(papers_api.answer_service, "submit_paper", fake_submit)
    resp = _client().post(
        "/api/v1/papers/8/submit",
        json={
            "items": [
                {"question_id": 501, "user_answer_md": "A"},
                {"question_id": 502, "user_answer_md": "x=1", "self_rated": 1},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["score"] == 7.0
    assert data["mastery"][0]["mastery_before"] is None
    assert data["mistake_question_ids"] == [502]
    assert captured["paper_id"] == 8
    assert len(captured["items"]) == 2


def test_submit_paper_rejects_bad_self_rating():
    resp = _client().post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501, "user_answer_md": "A", "self_rated": 0.7}]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_submit_paper_rejects_empty_items():
    resp = _client().post("/api/v1/papers/8/submit", json={"items": []})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_submit_paper_duplicate_returns_409(monkeypatch):
    from app.core.exceptions import ConflictError

    def boom(session, **kwargs):
        raise ConflictError("试卷已提交，请勿重复交卷")

    monkeypatch.setattr(papers_api.answer_service, "submit_paper", boom)
    resp = _client().post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501, "user_answer_md": "A"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_submit_paper_requires_student_role():
    resp = _client(_user("parent")).post(
        "/api/v1/papers/8/submit",
        json={"items": [{"question_id": 501, "user_answer_md": "A"}]},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_answer_row_out_accepts_numeric_from_orm():
    """出参把 DB 的 Decimal 转 float，避免 JSON 里出现字符串。"""
    row = Answer(
        id=1,
        user_id=50,
        paper_id=8,
        question_id=501,
        user_answer_md="A",
        is_correct=True,
        score=Decimal("2.50"),
        self_rated=Decimal("0.5"),
        time_spent_sec=3,
    )
    out = AnswerRowOut.model_validate(
        {
            "question_id": row.question_id,
            "user_answer_md": row.user_answer_md,
            "self_rated": float(row.self_rated),
            "is_correct": row.is_correct,
            "score": float(row.score),
            "time_spent_sec": row.time_spent_sec,
            "saved": True,
        }
    )
    assert out.score == 2.5
    assert out.self_rated == 0.5