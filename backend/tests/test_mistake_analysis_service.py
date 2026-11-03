"""S4-3 诊断服务：上下文构造、检索降级、1:1 覆盖、触发与跳过。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ai.analyze import DiagnosisContext, MistakeAnalysisError
from app.core.exceptions import NotFoundError
from app.models.enums import CauseType
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.services import mistake_analysis_service as svc
from app.services import task_service


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, rows_results=None, scalar_sequences=None):
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalar_sequences = list(scalar_sequences or [])
        self.rows_results = list(rows_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = 0
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    def scalars(self, statement):
        values = self.scalar_sequences.pop(0) if self.scalar_sequences else []
        return _Rows(values)

    def execute(self, statement):
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance):
        if getattr(instance, "id", None) is None:
            instance.id = 901
        self.added.append(instance)

    def flush(self):
        self.flushed += 1

    def delete(self, instance):
        self.deleted.append(instance)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _question() -> Question:
    question = Question(
        subject_id=7,
        stem_md="已知函数 $f(x)=x^2-4x+3$，求对称轴",
        stem_hash="h1",
        qtype="解答",
        difficulty=2,
        origin="upload",
        answer_md="$x=2$",
        verified=True,
    )
    question.id = 65
    return question


def _mistake(**overrides) -> Mistake:
    mistake = Mistake(
        user_id=1,
        question_id=65,
        status="待订正",
        correct_streak=0,
        created_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        my_answer_md="对称轴 x=1",
    )
    mistake.id = 12
    for key, value in overrides.items():
        setattr(mistake, key, value)
    return mistake


def _result(**overrides):
    from app.ai.analyze import MistakeAnalysisResult

    base = dict(
        cause_type=CauseType.CONCEPT,
        secondary_causes=[CauseType.CALC],
        error_step="你写的是「对称轴 x=1」，应为 x=2",
        explanation_md="配方得 $f(x)=(x-2)^2-1$，对称轴 $x=2$。易错点：顶点横坐标。",
        review_advice_md="复习配方法，对照笔记里的顶点公式。",
        confidence=0.82,
    )
    base.update(overrides)
    return MistakeAnalysisResult(**base)


def test_analyze_inserts_new_analysis(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): question},
        scalar_results=[None],
        rows_results=[[(133, "一元二次函数", Decimal("0.750000"))]],
    )
    monkeypatch.setattr(
        svc,
        "build_context",
        lambda *a, **k: DiagnosisContext(
            stem_md=question.stem_md, correct_answer_md="$x=2$", my_answer_md="对称轴 x=1",
            kp_names=["一元二次函数"],
        ),
    )
    monkeypatch.setattr(svc, "analyze_mistake", lambda ctx, **k: _result())

    analysis, summary = svc.analyze(session, user_id=1, mistake_id=12)

    assert isinstance(analysis, MistakeAnalysis)
    assert analysis.cause_type == "概念不清"
    assert analysis.secondary_causes == ["计算失误"]
    assert analysis.kp_ids == [133]
    assert analysis.prompt_version == "mistake_analyze_v2"
    assert analysis.confidence == Decimal("0.82")
    assert summary["confidence"] == pytest.approx(0.82)
    assert summary["secondary_causes"] == ["计算失误"]
    assert session.flushed >= 1
    assert session.commits == 0
    assert len(session.added) == 1


def test_analyze_updates_existing_row_in_place(monkeypatch):
    mistake, question = _mistake(), _question()
    existing = MistakeAnalysis(
        mistake_id=12,
        cause_type="计算失误",
        model="m",
        prompt_version="v1",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    existing.id = 7
    session = FakeSession(
        objects={(Mistake, 12): mistake, (Question, 65): question},
        scalar_results=[existing],
        rows_results=[[]],
    )
    monkeypatch.setattr(
        svc, "build_context", lambda *a, **k: DiagnosisContext(stem_md="x", my_answer_md="对称轴 x=1")
    )
    monkeypatch.setattr(svc, "analyze_mistake", lambda ctx, **k: _result())

    analysis, _summary = svc.analyze(session, user_id=1, mistake_id=12)

    assert analysis is existing
    assert existing.cause_type == "概念不清"
    assert existing.created_at != datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert existing.created_at.tzinfo is not None
    assert session.added == []


def test_analyze_other_user_raises_404():
    session = FakeSession(objects={(Mistake, 12): _mistake(user_id=2)})

    with pytest.raises(NotFoundError):
        svc.analyze(session, user_id=1, mistake_id=12)


def test_analyze_missing_mistake_raises_404():
    with pytest.raises(NotFoundError):
        svc.analyze(FakeSession(), user_id=1, mistake_id=999)


def test_analyze_propagates_analysis_error(monkeypatch):
    session = FakeSession(
        objects={(Mistake, 12): _mistake(), (Question, 65): _question()},
        rows_results=[[]],
    )

    def boom(_ctx, **_kwargs):
        raise MistakeAnalysisError("诊断失败（已尝试 3 次）")

    monkeypatch.setattr(svc, "analyze_mistake", boom)

    with pytest.raises(MistakeAnalysisError):
        svc.analyze(session, user_id=1, mistake_id=12)
    assert session.commits == 0


def test_build_context_degrades_when_retrieval_fails(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(rows_results=[[(133, "一元二次函数", Decimal("0.75"))]])

    def boom(*_a, **_k):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(svc.retrieval_service, "search_chunks", boom)

    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)

    assert ctx.notes == []
    assert ctx.kp_names == ["一元二次函数"]


def test_build_context_orders_kp_by_weight(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(
        rows_results=[[(133, "A", Decimal("0.9")), (116, "B", Decimal("0.8"))]]
    )
    monkeypatch.setattr(
        svc.retrieval_service, "search_chunks", lambda *a, **k: type("R", (), {"hits": []})()
    )

    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)

    assert ctx.kp_names == ["A", "B"]


def test_build_context_includes_note_hits(monkeypatch):
    mistake, question = _mistake(), _question()
    session = FakeSession(rows_results=[[]])
    hit = type("H", (), {"note_title": "二次函数", "snippet": "顶点式 $y=a(x-h)^2+k$"})()
    monkeypatch.setattr(
        svc.retrieval_service, "search_chunks", lambda *a, **k: type("R", (), {"hits": [hit]})()
    )

    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)

    assert ctx.notes == [("二次函数", "顶点式 $y=a(x-h)^2+k$")]


def test_build_context_falls_back_to_question_answer(monkeypatch):
    mistake = _mistake(correct_answer_md=None)
    question = _question()
    session = FakeSession(rows_results=[[]])
    monkeypatch.setattr(
        svc.retrieval_service, "search_chunks", lambda *a, **k: type("R", (), {"hits": []})()
    )

    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=question)

    assert ctx.correct_answer_md == "$x=2$"


def test_build_context_prefers_mistake_answer(monkeypatch):
    mistake = _mistake(correct_answer_md="学生自己的答案")
    session = FakeSession(rows_results=[[]])
    monkeypatch.setattr(
        svc.retrieval_service, "search_chunks", lambda *a, **k: type("R", (), {"hits": []})()
    )

    ctx = svc.build_context(session, user_id=1, mistake=mistake, question=_question())

    assert ctx.correct_answer_md == "学生自己的答案"


def test_prerequisite_names_use_parent_nodes():
    session = FakeSession(scalar_sequences=[["函数", "集合"]])
    assert svc._prerequisite_names(session, [133]) == ["函数", "集合"]


def test_has_analysis_true_and_false():
    assert svc.has_analysis(FakeSession(scalar_results=[1]), 12) is True
    assert svc.has_analysis(FakeSession(scalar_results=[None]), 12) is False


def test_enqueue_analysis_skips_when_analyzed(monkeypatch):
    owner = type("U", (), {"id": 1})()
    session = FakeSession(scalar_results=[12, 55])  # 归属校验命中，已有诊断 id=55
    called: list[dict] = []
    monkeypatch.setattr(task_service, "create_task", lambda *a, **k: called.append(k))

    result = svc.enqueue_analysis(session, owner=owner, mistake_id=12, queue=object())

    assert result is None
    assert called == []


def test_enqueue_analysis_force_path_creates_task(monkeypatch):
    owner = type("U", (), {"id": 1})()
    session = FakeSession(scalar_results=[12, 55])
    task = type("T", (), {"id": 88})()
    called: list[dict] = []
    monkeypatch.setattr(
        task_service, "create_task", lambda *a, **k: called.append(k) or task
    )

    result = svc.enqueue_analysis(
        session, owner=owner, mistake_id=12, queue=object(), force=True, skip_if_analyzed=False
    )

    assert result is task
    assert called[0]["name"] == "mistake.analyze"
    assert called[0]["payload"] == {"user_id": 1, "mistake_id": 12, "force": True}


def test_enqueue_analysis_other_user_404s(monkeypatch):
    owner = type("U", (), {"id": 1})()
    session = FakeSession(scalar_results=[None])
    monkeypatch.setattr(task_service, "create_task", lambda *a, **k: None)

    with pytest.raises(NotFoundError):
        svc.enqueue_analysis(session, owner=owner, mistake_id=12, queue=object())


def test_safe_enqueue_swallows_errors(monkeypatch):
    owner = type("U", (), {"id": 1})()
    session = FakeSession(scalar_results=[None])

    def boom(*_a, **_k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(svc, "enqueue_analysis", boom)

    assert svc.safe_enqueue(session, owner=owner, mistake_id=12, queue=object()) is False