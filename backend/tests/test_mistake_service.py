"""S4-2 错题服务：录入幂等、状态机、权限隔离、筛选 SQL、统计。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.mistake import Mistake
from app.models.question import Question
from app.schemas.mistake import MistakeCreateIn, MistakeUpdateIn
from app.services import mistake_service


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None, rows_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.rows_results = list(rows_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.scalar_statements: list[object] = []
        self.execute_statements: list[object] = []
        self._next_id = 500

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def execute(self, statement):
        self.execute_statements.append(statement)
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        # 模拟 DB 的 server_default=now()：真实 PG 在 commit 后才有值，
        # FakeSession 没有 flush/refresh，不补这一行 MistakeDetailOut.created_at 会拿到 None。
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime(2026, 11, 3, tzinfo=timezone.utc)
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _question(question_id: int = 65, *, answer: str | None = "B") -> Question:
    question = Question(
        subject_id=7, stem_md="已知函数 $f(x)=x^2-4x+3$", stem_hash="h1", qtype="解答",
        difficulty=2, origin="upload", answer_md=answer, verified=True,
    )
    question.id = question_id
    return question


def _mistake(mistake_id: int = 12, *, user_id: int = 1, status: str = "待订正", streak: int = 0) -> Mistake:
    mistake = Mistake(
        user_id=user_id, question_id=65, status=status, correct_streak=streak,
        created_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    mistake.id = mistake_id
    return mistake


def test_create_from_question_new_row_uses_question_answer():
    question = _question()
    session = FakeSession(objects={(Question, 65): question}, scalar_results=[None])
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65)
    )
    assert created is True
    assert session.commits == 1
    saved = session.added[0]
    assert isinstance(saved, Mistake)
    assert saved.correct_answer_md == "B"
    assert saved.status == MistakeStatus.TODO.value
    assert detail.question_id == 65


def test_create_from_question_reuses_existing_and_resets():
    existing = _mistake(status="已掌握", streak=2)
    session = FakeSession(
        objects={(Question, 65): _question(), (Mistake, 12): existing}, scalar_results=[existing]
    )
    detail, created = mistake_service.create_from_question(
        session, user_id=1, payload=MistakeCreateIn(question_id=65, my_answer_md="我又错了")
    )
    assert created is False
    assert existing.status == MistakeStatus.TODO.value
    assert existing.correct_streak == 0
    # d-1：录入不是复习，复用重置不得污染「复习时间」语义。
    assert existing.last_review_at is None
    assert existing.my_answer_md == "我又错了"
    assert session.commits == 1


def test_create_from_question_missing_question_raises_404():
    session = FakeSession(objects={})
    with pytest.raises(NotFoundError):
        mistake_service.create_from_question(session, user_id=1, payload=MistakeCreateIn(question_id=404))


def test_get_detail_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})
    with pytest.raises(NotFoundError):
        mistake_service.get_detail(session, user_id=1, mistake_id=12)


def test_update_mistake_rejects_null_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status=None)


def test_update_mistake_rejects_unknown_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MistakeUpdateIn(status="已通关")


def test_update_mistake_changes_answer_only():
    mistake = _mistake()
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): _question()},
        scalars_results=[[], []],  # kp 名 + cause 各一次（_detail 内部）
    )
    mistake_service.update_mistake(
        session, user_id=1, mistake_id=12, payload=MistakeUpdateIn(my_answer_md="x=2")
    )
    assert mistake.my_answer_md == "x=2"
    assert mistake.status == MistakeStatus.TODO.value
    assert session.commits == 1