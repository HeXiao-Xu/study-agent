"""S2-10 对齐服务：FakeSession 按表名分派，Fake 客户端不真实调用。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.subject import Subject
from app.models.user import User
from app.services import kp_align_service


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = list(vectors)
        self.calls: list[list[str]] = []

    def encode(self, texts, *, on_batch=None):
        self.calls.append(list(texts))
        return self.vectors.pop(0)


class FakeLLM:
    model = "fake-llm"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None):
        from app.ai.llm import LLMResponse

        self.calls += 1
        return LLMResponse(text=self.text, model="fake-llm", total_tokens=10)


class FakeSession:
    def __init__(
        self,
        *,
        kps: list[KnowledgePoint] | None = None,
        note_kps: list[NoteKp] | None = None,
        note: Note | None = None,
        user: User | None = None,
    ) -> None:
        self.kps = kps or []
        self.note_kps = note_kps or []
        self.note = note
        self.user = user
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0

    def scalars(self, statement: object):
        sql = str(statement)
        if "FROM note_kps" in sql:
            return list(self.note_kps)
        if "FROM knowledge_points" in sql:
            return list(self.kps)
        raise AssertionError(f"unexpected SQL: {sql}")

    def scalar(self, statement: object):
        raise AssertionError("unexpected scalar")

    def get(self, entity: type, pk: int):
        if entity is Note:
            return self.note
        if entity is User:
            return self.user
        raise AssertionError(f"unexpected get: {entity}")

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def _subject() -> Subject:
    subject = Subject(name="高中数学", code="math", stage="高中")
    subject.id = 1
    return subject


def _kp(
    kp_id: int,
    code: str,
    name: str,
    level: int,
    parent_id: int | None,
    embedding: list[float] | None,
) -> KnowledgePoint:
    kp = KnowledgePoint(
        subject_id=1,
        parent_id=parent_id,
        name=name,
        code=code,
        level=level,
        description=None,
        exam_weight=None,
        order_no=0,
        embedding=embedding,
    )
    kp.id = kp_id
    return kp


def _note(text: str, *, subject_id: int | None = 1) -> Note:
    note = Note(
        user_id=1,
        subject_id=subject_id,
        title="函数单调性复习",
        content_md=text,
        content_text=text,
        tags=["函数"],
        folder=None,
    )
    note.id = 1
    note.deleted_at = None
    return note


def _user() -> User:
    user = User(
        username="align_student",
        password_hash="hash",
        nickname="测试用户_1",
        grade="高一",
        role="student",
    )
    user.id = 1
    user.created_at = datetime.now(timezone.utc)
    return user


def test_ensure_kp_embeddings_only_fills_missing() -> None:
    missing = _kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, None)
    present = _kp(2, "MATH-FUNC-03", "函数的奇偶性", 2, None, [1.0, 0.0])
    embedder = FakeEmbedder([[[0.5, 0.5]]])
    session = FakeSession(kps=[missing, present])
    count = kp_align_service.ensure_kp_embeddings(
        session, subject_id=1, embedder=embedder  # type: ignore[arg-type]
    )
    assert count == 1
    assert missing.embedding == [0.5, 0.5]
    assert embedder.calls and len(embedder.calls[0]) == 1


def test_ensure_kp_embeddings_skips_when_none_missing() -> None:
    embedder = FakeEmbedder([])
    session = FakeSession(
        kps=[_kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, [1.0, 0.0])]
    )
    assert kp_align_service.ensure_kp_embeddings(
        session, subject_id=1, embedder=embedder  # type: ignore[arg-type]
    ) == 0
    assert embedder.calls == []


def test_retrieve_candidates_computes_cosine_and_path() -> None:
    root = _kp(1, "MATH", "高中数学", 1, None, [1.0, 0.0])
    child = _kp(2, "MATH-FUNC", "函数", 2, 1, [1.0, 0.0])
    leaf = _kp(3, "MATH-FUNC-02", "函数的单调性", 3, 2, [0.8, 0.6])
    session = FakeSession(kps=[root, child, leaf])
    note = _note("讨论函数的单调性")
    candidates = kp_align_service.retrieve_candidates(
        session, note=note, note_vec=[1.0, 0.0]  # type: ignore[arg-type]
    )
    by_id = {c.kp_id: c for c in candidates}
    assert by_id[3].cos == pytest.approx(0.8)
    assert by_id[3].path == "高中数学 / 函数 / 函数的单调性"
    assert by_id[3].keyword == 1.0
    assert by_id[3].prior == 1.0


def test_align_note_empty_text_returns_zeros() -> None:
    embedder = FakeEmbedder([])
    session = FakeSession(kps=[])
    stats = kp_align_service.align_note(
        session, note=_note(""), embedder=embedder, llm_client=FakeLLM("{}")  # type: ignore[arg-type]
    )
    assert (stats.candidates, stats.auto, stats.pending, stats.dropped) == (0, 0, 0, 0)
    assert embedder.calls == []


def test_align_note_classifies_auto_pending_drop() -> None:
    root = _kp(1, "MATH", "高中数学", 1, None, [1.0, 0.0])
    func = _kp(2, "MATH-FUNC", "函数", 2, 1, [1.0, 0.0])
    auto = _kp(3, "MATH-FUNC-02", "函数的单调性", 3, 2, [1.0, 0.0])
    pending = _kp(4, "MATH-FUNC-03", "函数的奇偶性", 3, 2, [0.7, 0.714142842854285])
    drop = _kp(5, "MATH-SEQ-01", "数列的概念与表示", 2, 1, [0.1, 0.99498743710662])
    session = FakeSession(kps=[root, func, auto, pending, drop])
    embedder = FakeEmbedder([[[1.0, 0.0]]])
    llm = FakeLLM(
        '{"matches":[{"kp_id":3,"confidence":0.9,"evidence":"单调性"},'
        '{"kp_id":4,"confidence":0.9,"evidence":"奇偶性"},'
        '{"kp_id":5,"confidence":0.9,"evidence":"数列"}]}'
    )
    stats = kp_align_service.align_note(
        session,
        note=_note("讨论函数的单调性与奇偶性"),  # type: ignore[arg-type]
        embedder=embedder,
        llm_client=llm,
    )
    assert (stats.candidates, stats.auto, stats.pending, stats.dropped) == (5, 1, 1, 3)
    rows = {(r.note_id, r.kp_id): r for r in session.added if isinstance(r, NoteKp)}
    assert rows[(1, 3)].confirmed is True
    assert rows[(1, 3)].source == "ai"
    assert rows[(1, 4)].confirmed is False
    assert Decimal("0.55") <= Decimal(str(rows[(1, 4)].confidence)) < Decimal("0.75")


def test_align_note_replaces_ai_rows_but_keeps_manual() -> None:
    kp = _kp(1, "MATH-FUNC-02", "函数的单调性", 2, None, [1.0, 0.0])
    old_ai = NoteKp(note_id=1, kp_id=9, confidence=Decimal("0.6"), source="ai", confirmed=False)
    manual = NoteKp(note_id=1, kp_id=8, confidence=Decimal("0.9"), source="manual", confirmed=True)
    session = FakeSession(kps=[kp], note_kps=[old_ai, manual])
    kp_align_service.align_note(
        session,
        note=_note("函数的单调性"),  # type: ignore[arg-type]
        embedder=FakeEmbedder([[[1.0, 0.0]]]),
        llm_client=FakeLLM('{"matches":[{"kp_id":1,"confidence":0.9,"evidence":"x"}]}'),
    )
    assert old_ai in session.deleted
    assert manual not in session.deleted


def test_confirm_pairs_updates_owned_rows_only() -> None:
    mine = NoteKp(note_id=1, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    mine.note = _note("x")
    mine.note.user_id = 1
    other = NoteKp(note_id=2, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    other.note = _note("y")
    other.note.user_id = 2
    session = FakeSession(note_kps=[mine, other])
    result = kp_align_service.confirm_pairs(
        session, viewer=_user(), pairs=[kp_align_service.AlignPair(note_id=1, kp_id=1),
                                        kp_align_service.AlignPair(note_id=2, kp_id=1)]
    )
    assert result.confirmed == 1
    assert result.skipped == 1
    assert mine.confirmed is True
    assert mine.source == "manual"
    assert other.confirmed is False


def test_reject_pairs_deletes_only_unconfirmed_ai_rows() -> None:
    pending = NoteKp(note_id=1, kp_id=1, confidence=Decimal("0.6"), source="ai", confirmed=False)
    confirmed = NoteKp(note_id=1, kp_id=2, confidence=Decimal("0.9"), source="manual", confirmed=True)
    pending.note = _note("x")
    confirmed.note = pending.note
    session = FakeSession(note_kps=[pending, confirmed])
    result = kp_align_service.reject_pairs(
        session,
        viewer=_user(),
        pairs=[kp_align_service.AlignPair(note_id=1, kp_id=1),
               kp_align_service.AlignPair(note_id=1, kp_id=2)],
    )
    assert result.deleted == 1
    assert result.skipped == 1
    assert pending in session.deleted
    assert confirmed not in session.deleted