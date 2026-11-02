"""S4-1 题库服务：判重两道闸、对齐阈值、权限、事务边界。"""
from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.ai.align.extractor import AlignError, LlmMatch
from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.subject import Subject
from app.models.user import User
from app.schemas.question import (
    KpRefOut,
    QuestionCreateIn,
    QuestionMergeIn,
    QuestionSplitIn,
    QuestionUpdateIn,
)
from app.services import question_service
from app.utils.pagination import PageParams, SortParams


class FakeSession:
    """按调用顺序喂 scalar/scalars 结果：服务里的查询是确定的，顺序断言最直观。"""

    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.scalar_statements: list[object] = []
        self._next_id = 100

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [1.0, 0.0]
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        return [self.vector for _ in texts]


def _user(role: str = "student", user_id: int = 1) -> User:
    user = User(username=f"{role}_q", password_hash="hash", nickname="测试用户_1", grade="高一", role=role)
    user.id = user_id
    return user


def _kp(kp_id: int, name: str, *, level: int = 2, parent_id: int | None = None,
        embedding: list[float] | None = None) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1, name=name, code=f"kp.{kp_id}", level=level,
        parent_id=parent_id, embedding=embedding or [1.0, 0.0],
    )
    kp.id = kp_id
    return kp


def test_normalize_stem_strips_number_and_spaces() -> None:
    assert question_service.normalize_stem("  12． 已知  函数 f(x)  ") == "已知函数f(x)"


def test_normalize_stem_fullwidth_equals_halfwidth() -> None:
    left = question_service.compute_stem_hash("1. 已知（a，b），求 a+b。")
    right = question_service.compute_stem_hash("已知(a,b),求a+b")
    assert left == right


def test_stem_hash_changes_when_number_changes() -> None:
    assert question_service.compute_stem_hash("1. 求 2+3") != question_service.compute_stem_hash("1. 求 2+4")


def test_check_duplicate_hits_by_hash_first() -> None:
    existing = Question(subject_id=1, stem_md="已知函数", stem_hash="h", qtype="填空", difficulty=3)
    existing.id = 7
    session = FakeSession(scalar_results=[existing])
    hit = question_service.check_duplicate(session, subject_id=1, stem_hash="h", vec=[1.0, 0.0])
    assert hit is existing


def test_check_duplicate_falls_back_to_vector() -> None:
    near = Question(subject_id=1, stem_md="已知函数 f(x)", stem_hash="other", qtype="填空", difficulty=3)
    near.id = 8
    near.embedding = [1.0, 0.0]
    session = FakeSession(scalar_results=[None, near])
    hit = question_service.check_duplicate(session, subject_id=1, stem_hash="new", vec=[1.0, 0.0])
    assert hit is near


def test_check_duplicate_returns_none_when_far() -> None:
    far = Question(subject_id=1, stem_md="无关", stem_hash="other", qtype="填空", difficulty=3)
    far.id = 9
    far.embedding = [0.0, 1.0]
    session = FakeSession(scalar_results=[None, far])
    assert question_service.check_duplicate(session, subject_id=1, stem_hash="new", vec=[1.0, 0.0]) is None


def _matcher(*matches: LlmMatch):
    """假 LLM：返回给定匹配，忽略 prompt 参数。"""

    def _choose(**_: object) -> list[LlmMatch]:
        return list(matches)

    return _choose


def test_align_keeps_only_high_score() -> None:
    related = _kp(1, "函数的单调性")
    unrelated = _kp(2, "立体几何", embedding=[0.0, 1.0])
    session = FakeSession(scalars_results=[[related, unrelated]])
    links = question_service.align_knowledge_points(
        session,
        subject_id=1,
        text="已知函数的单调性，求最值",
        kp_names=["函数的单调性"],
        vec=[1.0, 0.0],
        matcher=_matcher(LlmMatch(kp_id=1, confidence=0.9, evidence="单调性")),
    )
    assert [kp_id for kp_id, _ in links] == [1]
    assert links[0][1] >= Decimal("0.75")


def test_align_limits_to_three_links() -> None:
    kps = [_kp(index, "函数的单调性") for index in range(1, 6)]
    session = FakeSession(scalars_results=[kps])
    links = question_service.align_knowledge_points(
        session,
        subject_id=1,
        text="函数的单调性",
        kp_names=["函数的单调性"],
        vec=[1.0, 0.0],
        matcher=_matcher(*[LlmMatch(kp_id=index, confidence=0.9, evidence="x") for index in range(1, 6)]),
    )
    assert len(links) == 3


def test_create_question_raises_conflict_on_duplicate() -> None:
    existing = Question(subject_id=1, stem_md="已知", stem_hash="dup", qtype="填空", difficulty=3)
    existing.id = 11
    session = FakeSession(
        objects={(Subject, 1): Subject(name="数学"), (Question, 11): existing},
        scalar_results=[existing],
    )
    payload = QuestionCreateIn(subject_id=1, stem_md="1. 已知", qtype="填空", difficulty=3)
    with pytest.raises(ConflictError):
        question_service.create_question(session, payload=payload, creator=_user(), embedder=FakeEmbedder())
    assert session.commits == 0


def test_create_question_persists_and_links_manual_kps() -> None:
    subject = Subject(name="数学")
    session = FakeSession(
        objects={(Subject, 1): subject},
        scalar_results=[None, None],
        scalars_results=[[7]],
    )
    payload = QuestionCreateIn(subject_id=1, stem_md="1. 已知函数 f(x)=x²，求 f(1)。",
                               qtype="解答", difficulty=2, kp_ids=[7])
    question = question_service.create_question(
        session, payload=payload, creator=_user(), embedder=FakeEmbedder()
    )
    assert question.stem_hash == question_service.compute_stem_hash(payload.stem_md)
    assert question.embedding == [1.0, 0.0]
    links = [row for row in session.added if isinstance(row, QuestionKp)]
    assert [(row.kp_id, row.weight) for row in links] == [(7, Decimal("1.000000"))]
    assert session.commits == 1


def test_ensure_can_edit_rejects_other_students_question() -> None:
    question = Question(subject_id=1, stem_md="已知", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 5
    question.created_by = 99
    with pytest.raises(ForbiddenError):
        question_service.ensure_can_edit(question, _user(role="student", user_id=1))


def test_ensure_can_edit_allows_teacher() -> None:
    question = Question(subject_id=1, stem_md="已知", stem_hash="h", qtype="填空", difficulty=3)
    question.created_by = 99
    question_service.ensure_can_edit(question, _user(role="teacher", user_id=1))


def test_update_question_recomputes_hash_and_embedding() -> None:
    question = Question(subject_id=1, stem_md="1. 旧题干内容", stem_hash="old", qtype="填空", difficulty=3)
    question.id = 3
    question.created_by = 1
    question.embedding = [0.0, 1.0]
    session = FakeSession(objects={(Question, 3): question}, scalar_results=[None], scalars_results=[[], []])
    updated = question_service.update_question(
        session,
        question_id=3,
        payload=QuestionUpdateIn(stem_md="1. 新题干内容"),
        viewer=_user(user_id=1),
        embedder=FakeEmbedder(),
    )
    assert updated.stem_md == "1. 新题干内容"
    assert updated.stem_hash == question_service.compute_stem_hash("1. 新题干内容")
    assert updated.embedding == [1.0, 0.0]
    assert session.commits == 1


def test_delete_question_clears_links() -> None:
    question = Question(subject_id=1, stem_md="题干", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 4
    question.created_by = 1
    link = QuestionKp(question_id=4, kp_id=9, weight=Decimal("1.0"))
    session = FakeSession(objects={(Question, 4): question}, scalars_results=[[link]])
    question_service.delete_question(session, question_id=4, viewer=_user(user_id=1))
    assert link in session.deleted
    assert question in session.deleted
    assert session.commits == 1


def test_merge_rejects_cross_subject() -> None:
    left = Question(subject_id=1, stem_md="甲题目内容", stem_hash="a", qtype="填空", difficulty=3)
    left.id = 1
    right = Question(subject_id=2, stem_md="乙题目内容", stem_hash="b", qtype="填空", difficulty=3)
    right.id = 2
    session = FakeSession(objects={(Question, 1): left, (Question, 2): right})
    with pytest.raises(InvalidParamError):
        question_service.merge_questions(
            session, ids=[1, 2], viewer=_user(role="teacher"), embedder=FakeEmbedder()
        )


def test_split_rejects_missing_marker() -> None:
    question = Question(subject_id=1, stem_md="1. 甲题 2. 乙题", stem_hash="h", qtype="填空", difficulty=3)
    question.id = 5
    question.created_by = 1
    session = FakeSession(objects={(Question, 5): question})
    with pytest.raises(InvalidParamError):
        question_service.split_question(
            session, question_id=5, split_at="3.", viewer=_user(user_id=1), embedder=FakeEmbedder()
        )


def test_persist_question_maps_stem_hash_unique_violation_to_conflict() -> None:
    class UniqueViolationSession(FakeSession):
        def flush(self) -> None:
            raise IntegrityError(
                "INSERT INTO questions ...",
                {},
                Exception('duplicate key value violates unique constraint "uq_questions_subject_stem_hash"'),
            )

    session = UniqueViolationSession()
    with pytest.raises(ConflictError):
        question_service._persist_question(
            session,
            subject_id=1,
            origin="upload",
            source_file_id=None,
            stem_md="1. 已知函数 f(x)=x²，求 f(1)。",
            options_json=None,
            answer_md=None,
            analysis_md=None,
            qtype="解答",
            difficulty=2,
            tags=None,
            verified=False,
            embedding=[1.0, 0.0],
            created_by=1,
            links=[],
        )
    assert session.rollbacks == 1


def test_kp_guard_rejects_cross_subject_and_dedupes_ids() -> None:
    subject = Subject(name="数学")
    foreign_session = FakeSession(
        objects={(Subject, 1): subject}, scalar_results=[None, None], scalars_results=[[]]
    )
    foreign_payload = QuestionCreateIn(
        subject_id=1, stem_md="1. 已知函数 f(x)=x²，求 f(1)。", qtype="解答", difficulty=2, kp_ids=[99]
    )
    with pytest.raises(InvalidParamError):
        question_service.create_question(
            foreign_session, payload=foreign_payload, creator=_user(), embedder=FakeEmbedder()
        )
    assert foreign_session.commits == 0

    session = FakeSession(
        objects={(Subject, 1): subject}, scalar_results=[None, None], scalars_results=[[7, 9]]
    )
    payload = QuestionCreateIn(
        subject_id=1, stem_md="1. 已知函数 f(x)=x²，求 f(1)。", qtype="解答", difficulty=2, kp_ids=[7, 7, 9]
    )
    question_service.create_question(session, payload=payload, creator=_user(), embedder=FakeEmbedder())
    links = [row for row in session.added if isinstance(row, QuestionKp)]
    assert [row.kp_id for row in links] == [7, 9]


def test_create_question_rolls_back_when_commit_fails() -> None:
    class CommitFailingSession(FakeSession):
        def commit(self) -> None:
            raise RuntimeError("database unavailable")

    subject = Subject(name="数学")
    session = CommitFailingSession(objects={(Subject, 1): subject}, scalar_results=[None, None])
    payload = QuestionCreateIn(subject_id=1, stem_md="1. 已知函数 f(x)=x²，求 f(1)。", qtype="解答", difficulty=2)
    with pytest.raises(RuntimeError):
        question_service.create_question(session, payload=payload, creator=_user(), embedder=FakeEmbedder())
    assert session.rollbacks == 1


def test_align_uses_llm_selection_and_combine_weight() -> None:
    related = _kp(1, "函数的单调性")
    unrelated = _kp(2, "立体几何", embedding=[0.0, 1.0])
    session = FakeSession(scalars_results=[[related, unrelated]])
    links = question_service.align_knowledge_points(
        session,
        subject_id=1,
        text="已知函数的单调性，求最值",
        kp_names=["函数的单调性"],
        vec=[1.0, 0.0],
        matcher=_matcher(LlmMatch(kp_id=1, confidence=0.9, evidence="单调性")),
    )
    assert links == [(1, Decimal("0.93"))]


def test_align_ignores_llm_kp_id_outside_candidates() -> None:
    related = _kp(1, "函数的单调性")
    session = FakeSession(scalars_results=[[related]])
    links = question_service.align_knowledge_points(
        session,
        subject_id=1,
        text="已知函数的单调性，求最值",
        kp_names=["函数的单调性"],
        vec=[1.0, 0.0],
        matcher=_matcher(LlmMatch(kp_id=99, confidence=0.9, evidence="幻觉节点")),
    )
    assert links == []


def test_align_ignores_llm_low_confidence() -> None:
    related = _kp(1, "函数的单调性")
    session = FakeSession(scalars_results=[[related]])
    links = question_service.align_knowledge_points(
        session,
        subject_id=1,
        text="已知函数的单调性，求最值",
        kp_names=["函数的单调性"],
        vec=[1.0, 0.0],
        matcher=_matcher(LlmMatch(kp_id=1, confidence=0.3, evidence="不太确定")),
    )
    assert links == []


def test_align_falls_back_to_score_when_llm_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    related = _kp(1, "函数的单调性")
    session = FakeSession(scalars_results=[[related]])

    def _boom(**_: object) -> list[LlmMatch]:
        raise AlignError("LLM 不可用")

    with caplog.at_level(logging.WARNING):
        links = question_service.align_knowledge_points(
            session,
            subject_id=1,
            text="已知函数的单调性，求最值",
            kp_names=["函数的单调性"],
            vec=[1.0, 0.0],
            matcher=_boom,
        )
    assert links == [(1, Decimal("0.93"))]
    assert any(record.getMessage() == "question_align_llm_failed" for record in caplog.records)


def test_split_excludes_source_from_duplicate_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """原题仍在库里，拆出的两半都是它的子串；判重必须排除源题，否则必然自撞 409。"""
    question = Question(
        subject_id=1, stem_md="1. 甲题内容足够长 2. 乙题内容足够长", stem_hash="h", qtype="填空", difficulty=3
    )
    question.id = 5
    question.created_by = 1
    session = FakeSession(objects={(Question, 5): question})
    calls: list[list[int] | None] = []

    def fake_check(session_, *, subject_id, stem_hash, vec=None, exclude_ids=None):
        calls.append(exclude_ids)
        return None

    monkeypatch.setattr(question_service, "check_duplicate", fake_check)
    question_service.split_question(
        session, question_id=5, split_at="2.", viewer=_user(user_id=1), embedder=FakeEmbedder()
    )
    assert calls == [[5], [5]]


def test_merge_excludes_sources_from_duplicate_check(monkeypatch: pytest.MonkeyPatch) -> None:
    left = Question(subject_id=1, stem_md="甲题目内容足够长", stem_hash="a", qtype="填空", difficulty=3)
    left.id = 1
    left.created_by = 1
    right = Question(subject_id=1, stem_md="乙题目内容足够长", stem_hash="b", qtype="填空", difficulty=3)
    right.id = 2
    right.created_by = 1
    session = FakeSession(objects={(Question, 1): left, (Question, 2): right})
    calls: list[list[int] | None] = []

    def fake_check(session_, *, subject_id, stem_hash, vec=None, exclude_ids=None):
        calls.append(exclude_ids)
        return None

    monkeypatch.setattr(question_service, "check_duplicate", fake_check)
    question_service.merge_questions(session, ids=[2, 1, 2], viewer=_user(role="teacher"), embedder=FakeEmbedder())
    assert calls == [[1, 2]]


def test_check_duplicate_exclude_ids_adds_sql_filter() -> None:
    session = FakeSession()
    question_service.check_duplicate(
        session, subject_id=1, stem_hash="h", vec=[1.0, 0.0], exclude_ids=[4, 9]
    )
    assert len(session.scalar_statements) == 2
    assert all("NOT IN" in str(statement) for statement in session.scalar_statements)

    baseline = FakeSession()
    question_service.check_duplicate(baseline, subject_id=1, stem_hash="h", vec=[1.0, 0.0])
    assert len(baseline.scalar_statements) == 2
    assert all("NOT IN" not in str(statement) for statement in baseline.scalar_statements)


def test_ensure_not_referenced_blocks_only_when_mistakes_reference_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Result:
        def __init__(self, row: object) -> None:
            self.row = row

        def first(self) -> object:
            return self.row

    class _RefSession(FakeSession):
        def __init__(self, row: object) -> None:
            super().__init__()
            self.row = row

        def execute(self, statement, params=None):
            return _Result(self.row)

    monkeypatch.setattr(question_service, "_mistakes_table_exists", lambda session: True)
    with pytest.raises(ConflictError):
        question_service._ensure_not_referenced(_RefSession((1,)), [7])
    question_service._ensure_not_referenced(_RefSession(None), [7])


def test_build_questions_query_kp_filter_uses_exists_not_join() -> None:
    stmt = question_service.build_questions_query(filters=question_service.QuestionFilters(kp_id=7))
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "EXISTS" in sql.upper()
    assert "JOIN" not in sql.upper()


def test_build_questions_query_keyword_escapes_like_wildcards() -> None:
    stmt = question_service.build_questions_query(
        filters=question_service.QuestionFilters(keyword="100%_x")
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert r"100\%\_x" in sql
    assert "ESCAPE" in sql


def test_build_questions_query_verified_filter_branches() -> None:
    def _sql(verified: bool | None) -> str:
        stmt = question_service.build_questions_query(
            filters=question_service.QuestionFilters(verified=verified)
        )
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "questions.verified IS true" in _sql(True)
    assert "questions.verified IS false" in _sql(False)
    assert "questions.verified IS" not in _sql(None)


def test_update_question_rejects_null_for_non_nullable_fields() -> None:
    for name in ("qtype", "difficulty", "origin", "verified"):
        question = Question(
            subject_id=1,
            stem_md="已知函数内容",
            stem_hash="h",
            qtype="填空",
            difficulty=3,
            origin="upload",
            verified=False,
        )
        question.id = 3
        question.created_by = 1
        session = FakeSession(objects={(Question, 3): question})
        payload = QuestionUpdateIn(**{name: None})
        with pytest.raises(InvalidParamError):
            question_service.update_question(
                session,
                question_id=3,
                payload=payload,
                viewer=_user(user_id=1),
                embedder=FakeEmbedder(),
            )
        assert session.commits == 0
        assert getattr(question, name) is not None


def test_update_question_maps_update_unique_violation_to_conflict() -> None:
    class UniqueViolationSession(FakeSession):
        def commit(self) -> None:
            raise IntegrityError(
                "UPDATE questions ...",
                {},
                Exception('duplicate key value violates unique constraint "uq_questions_subject_stem_hash"'),
            )

    question = Question(
        subject_id=1,
        stem_md="已知函数内容",
        stem_hash="h",
        qtype="填空",
        difficulty=3,
        origin="upload",
        verified=False,
    )
    question.id = 3
    question.created_by = 1
    session = UniqueViolationSession(objects={(Question, 3): question})
    with pytest.raises(ConflictError):
        question_service.update_question(
            session,
            question_id=3,
            payload=QuestionUpdateIn(answer_md="答案"),
            viewer=_user(user_id=1),
            embedder=FakeEmbedder(),
        )
    assert session.rollbacks == 1


def test_update_question_persists_punctuation_only_stem_edit() -> None:
    old_stem = "1. 已知函数 f(x)，求 f(1)"
    new_stem = "1. 已知函数 f(x)，求 f(1)。"
    assert question_service.normalize_stem(old_stem) == question_service.normalize_stem(new_stem)
    question = Question(
        subject_id=1,
        stem_md=old_stem,
        stem_hash="old",
        qtype="填空",
        difficulty=3,
        origin="upload",
        verified=False,
    )
    question.id = 3
    question.created_by = 1
    question.embedding = [0.0, 1.0]
    session = FakeSession(
        objects={(Question, 3): question}, scalar_results=[None], scalars_results=[[], []]
    )
    updated = question_service.update_question(
        session,
        question_id=3,
        payload=QuestionUpdateIn(stem_md=new_stem),
        viewer=_user(user_id=1),
        embedder=FakeEmbedder(),
    )
    assert updated.stem_md == new_stem
    assert updated.stem_hash == question_service.compute_stem_hash(new_stem)
    assert updated.embedding == [1.0, 0.0]
    assert session.commits == 1


def test_question_shape_validation_rejects_choice_without_options() -> None:
    with pytest.raises(ValidationError):
        QuestionCreateIn(subject_id=1, stem_md="已知函数内容超过五字", qtype="单选", difficulty=2)

    question = Question(
        subject_id=1,
        stem_md="已知函数内容",
        stem_hash="h",
        qtype="解答",
        difficulty=3,
        origin="upload",
        verified=False,
    )
    question.id = 3
    question.created_by = 1
    session = FakeSession(objects={(Question, 3): question})
    with pytest.raises(InvalidParamError):
        question_service.update_question(
            session,
            question_id=3,
            payload=QuestionUpdateIn(qtype="单选"),
            viewer=_user(user_id=1),
            embedder=FakeEmbedder(),
        )
    assert session.commits == 0


def test_list_questions_appends_id_tiebreaker(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _Page:
        items: list[object] = []
        total = 0
        page = 1
        page_size = 20

    def fake_paginate(session, stmt, page, *, item_model):
        captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        return _Page()

    monkeypatch.setattr(question_service, "paginate_query", fake_paginate)
    question_service.list_questions(
        session=None,
        filters=question_service.QuestionFilters(),
        page=PageParams(),
        sort=SortParams(),
    )
    assert "questions.created_at DESC" in captured["sql"]
    assert "questions.id DESC" in captured["sql"]


def test_kp_ref_out_serializes_weight_as_float() -> None:
    ref = KpRefOut(kp_id=1, kp_name="函数的单调性", kp_code="kp.1", weight=Decimal("0.930000"))
    assert isinstance(ref.weight, float)
    assert ref.model_dump(mode="json")["weight"] == 0.93
