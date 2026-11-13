"""S5-3 导出接口：鉴权、状态码、PDF 响应头与渲染失败。"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.paper import Paper
from app.models.subject import Subject
from app.models.user import User
from app.services import pdf_service

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


def _user(role: str = "student", user_id: int = 50) -> User:
    user = User(username=f"{role}_s53", nickname=role, grade="高二", role=role, password_hash="x")
    user.id = user_id
    return user


def _paper(paper_id: int = 7, *, user_id: int = 50, question_ids: list[int] | None = None) -> Paper:
    paper = Paper(
        user_id=user_id,
        title="期中卷",
        constraint_json={"seed": 7},
        question_ids=question_ids if question_ids is not None else [501],
        total_score=3,
        duration_min=60,
        status="草稿",
        generated_by="manual",
    )
    paper.id = paper_id
    paper.created_at = NOW
    return paper


class ExportSession:
    """get_paper 查询顺序：get(Paper) → details rows → kp rows；导出再 get(Subject)。"""

    def __init__(self, *, paper: Paper, detail_rows: list[tuple]) -> None:
        self.paper = paper
        self.results = [list(detail_rows), [(501, 117)]]
        self.user = _user()

    def get(self, model, pk):  # noqa: ANN001, ANN201
        if model is Paper:
            return self.paper if self.paper.id == pk else None
        if model is Subject:
            subject = Subject(name="高中数学", code="math")
            subject.id = pk
            return subject
        return None

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


def _detail_rows() -> list[tuple]:
    return [
        (
            501,
            7,
            "单选",
            2,
            "题干 501 $x^2$",
            [{"key": "A", "text": "选项 A"}],
            "答案 501",
            None,
            True,
            "exam",
        )
    ]


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session: ExportSession, user: User) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role).token
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.fixture()
def fake_renderer(monkeypatch):
    calls: dict[str, str] = {}

    def _render(html_text: str, header: str, footer: str) -> bytes:
        calls["html"] = html_text
        return b"%PDF-1.4 fake pdf"

    monkeypatch.setattr(pdf_service, "render_pdf", _render)
    return calls


def test_export_requires_login_returns_401(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    app.dependency_overrides[get_db] = lambda: session
    response = TestClient(app).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 401


def test_export_forbids_other_user_returns_403(fake_renderer) -> None:
    session = ExportSession(paper=_paper(user_id=99), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 403
    assert response.json()["code"] == 40300


def test_export_missing_paper_returns_404(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/999/export.pdf")
    assert response.status_code == 404
    assert response.json()["code"] == 40400


def test_export_empty_paper_returns_409(fake_renderer) -> None:
    session = ExportSession(paper=_paper(question_ids=[]), detail_rows=[])
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")
    assert response.status_code == 409
    assert response.json()["message"] == "试卷没有可导出的题目"


def test_export_questions_returns_pdf_bytes(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert 'filename="paper-7-questions.pdf"' in disposition
    assert f"filename*=UTF-8''{quote('期中卷-题干卷.pdf')}" in disposition
    assert "答案：" not in fake_renderer["html"]


def test_export_answers_returns_filename_with_answer_label(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf?variant=answers")

    assert response.status_code == 200
    assert (
        f"filename*=UTF-8''{quote('期中卷-答案卷.pdf')}"
        in response.headers["content-disposition"]
    )
    assert "答案：" in fake_renderer["html"]


def test_export_invalid_variant_returns_422(fake_renderer) -> None:
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf?variant=both")
    assert response.status_code == 422
    assert response.json()["code"] == 42200


def test_export_renderer_error_returns_500(monkeypatch) -> None:
    def _boom(html_text: str, header: str, footer: str) -> bytes:
        raise RuntimeError("浏览器崩了")

    monkeypatch.setattr(pdf_service, "render_pdf", _boom)
    session = ExportSession(paper=_paper(), detail_rows=_detail_rows())
    response = _client(session, _user()).get("/api/v1/papers/7/export.pdf")

    assert response.status_code == 500
    assert response.json()["code"] == 50000
    assert "浏览器崩了" not in response.text