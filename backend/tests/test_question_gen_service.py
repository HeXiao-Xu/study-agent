"""S4-4 变式题服务：触发校验、生成编排、入库幂等。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.gen import GeneratedVariant, VariantVerificationError
from app.core.exceptions import ConflictError, NotFoundError
from app.models.mistake import Mistake
from app.models.mistake_analysis import MistakeAnalysis
from app.models.question import Question
from app.services import question_gen_service as svc


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, rows_results=None):
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.rows_results = list(rows_results or [])
        self.added: list[object] = []
        self.flushed = 0
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return _Rows([])

    def execute(self, statement):
        return _Rows(self.rows_results.pop(0) if self.rows_results else [])

    def add(self, instance):
        if getattr(instance, "id", None) is None:
            instance.id = 901
        self.added.append(instance)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _mistake() -> Mistake:
    return Mistake(id=43, user_id=5, question_id=100, status="待订正", correct_streak=0)


def _question() -> Question:
    return Question(
        id=100, subject_id=7, stem_md="等差数列 $a_1=2$，公差 $d=3$，求 $a_{10}$。",
        stem_hash="h", qtype="解答", difficulty=2, origin="upload",
        answer_md="$29$", verified=True,
    )


def _analysis(**overrides) -> MistakeAnalysis:
    base = dict(
        id=7, mistake_id=43, cause_type="审题偏差", kp_ids=[12],
        model="qwen-plus", prompt_version="mistake_analyze_v2",
        similar_questions_json=None,
    )
    base.update(overrides)
    return MistakeAnalysis(**base)


def _session(*, analysis=None, question=None, mistake=None) -> FakeSession:
    mistake = mistake or _mistake()
    question = question or _question()
    analysis = analysis if analysis is not None else _analysis()
    return FakeSession(
        objects={
            (Mistake, 43): mistake,
            (Question, 100): question,
            (MistakeAnalysis, None): analysis,
        },
        scalar_results=[analysis],
    )


def _variant(answer="$13$") -> GeneratedVariant:
    return GeneratedVariant(
        stem_md="等差数列 $a_1=1$，公差 $d=2$，求 $a_7$。",
        options=None,
        answer_md=answer,
        analysis_md="用 $a_n=a_1+(n-1)d$ 得 $a_7=13$。",
        qtype="解答",
        difficulty=3,
    )


class _Owner:
    id = 5


def test_enqueue_variants_requires_analysis(monkeypatch):
    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), _question(), None))

    with pytest.raises(ConflictError, match="先完成错因诊断"):
        svc.enqueue_variants(FakeSession(), owner=_Owner(), mistake_id=43, queue=object())


def test_enqueue_variants_rejects_short_stem(monkeypatch):
    short = _question()
    short.stem_md = "求值"
    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), short, _analysis()))

    with pytest.raises(ConflictError, match="题干太短"):
        svc.enqueue_variants(FakeSession(), owner=_Owner(), mistake_id=43, queue=object())


def test_enqueue_variants_creates_task(monkeypatch):
    created: dict = {}

    def _create_task(session, *, owner, name, payload, queue):
        created.update(name=name, payload=payload)
        return type("T", (), {"id": 88})()

    monkeypatch.setattr(svc, "_load_owned", lambda *a, **k: (_mistake(), _question(), _analysis()))
    monkeypatch.setattr("app.services.task_service.create_task", _create_task)

    task = svc.enqueue_variants(FakeSession(), owner=_Owner(), mistake_id=43, queue=object())

    assert task.id == 88
    assert created["name"] == "mistake.variants"
    assert created["payload"] == {"user_id": 5, "mistake_id": 43}


def test_run_generation_keeps_only_passed_variants(monkeypatch):
    session = _session()

    # 假生成器按 ctx.count 返回（重生成时只补缺的条数），否则重生成轮会越补越多
    def _fake_generate(ctx, **kwargs):
        return [_variant("$13$"), _variant("$99$")][: ctx.count]

    # 第 1 轮：第一道复算一致、第二道不一致；第 2 轮补生成的那道复算一致
    answers = iter(["$13$", "$100$", "$13$"])
    monkeypatch.setattr(svc, "generate_variants", _fake_generate)
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: next(answers))

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["requested"] == 3
    assert summary["passed"] == 2
    assert summary["rejected"] == 1
    assert summary["rounds"] == 2
    assert payload["version"] == 1
    assert len(payload["items"]) == 2
    assert payload["items"][0]["answer_md"] == "$13$"
    assert payload["items"][0]["self_check"]["verified_answer_md"] == "$13$"
    assert payload["rejected"][0]["reason"]
    assert session.commits == 0  # 任务内不 commit


def test_run_generation_clamps_difficulty_around_original(monkeypatch):
    session = _session()
    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant()][: ctx.count])
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: "$13$")

    svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    # 原题难度 2 → 允许 1..3；假生成器给的是 3，落在区间内不被改
    assert payload["items"][0]["difficulty"] == 3


def test_run_generation_marks_task_result_even_if_all_rejected(monkeypatch):
    session = _session()
    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant("$1$")][: ctx.count])
    monkeypatch.setattr(svc, "verify_answer", lambda ctx, **k: "$2$")

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["passed"] == 0
    assert payload["items"] == []
    assert payload["stats"]["rejected"] >= 1
    assert payload["stats"]["rounds"] == 3  # 1 次生成 + 2 次重生成，之后放弃


def test_run_generation_treats_verification_error_as_rejected(monkeypatch):
    session = _session()

    def _boom(ctx, **kwargs):
        raise VariantVerificationError("炸了")

    monkeypatch.setattr(svc, "generate_variants", lambda ctx, **k: [_variant()][: ctx.count])
    monkeypatch.setattr(svc, "verify_answer", _boom)

    summary = svc.run_generation(session, user_id=5, mistake_id=43)

    payload = session.objects[(MistakeAnalysis, None)].similar_questions_json
    assert summary["passed"] == 0
    assert payload["rejected"][0]["reason"] == "复算调用失败"


def test_accept_variant_creates_question_and_marks_json(monkeypatch):
    session = _session()
    payload = {
        "version": 1,
        "items": [
            {"variant_id": "abc12345", "stem_md": "求 $2+2$ 的值。", "options": None,
             "answer_md": "$4$", "analysis_md": "直接相加得 4。", "qtype": "解答",
             "difficulty": 1, "kp_ids": [12],
             "self_check": {"status": "passed", "attempts": 1},
             "accepted_question_id": None, "accepted_at": None}
        ],
        "rejected": [],
        "stats": {"requested": 1, "passed": 1, "rejected": 0, "rounds": 1},
    }
    session.objects[(MistakeAnalysis, None)].similar_questions_json = payload

    class _Created:
        id = 128

    captured: dict = {}

    def _fake_create(session, **kwargs):
        captured.update(kwargs)
        return _Created(), True

    monkeypatch.setattr(svc.question_service, "create_generated_question", _fake_create)
    monkeypatch.setattr(
        svc, "_kp_links", lambda session, question_id: [(12, Decimal("1.000000"))]
    )

    question, created = svc.accept_variant(
        session, owner=_Owner(), mistake_id=43, variant_id="abc12345"
    )

    assert created is True and question.id == 128
    item = session.objects[(MistakeAnalysis, None)].similar_questions_json["items"][0]
    assert item["accepted_question_id"] == 128
    assert item["accepted_at"]
    assert session.commits == 1
    # 入库题继承原题的 subject 与知识点链接，创建者记为当前用户
    assert captured["subject_id"] == 7
    assert captured["created_by"] == 5
    assert captured["links"] == [(12, Decimal("1.000000"))]


def test_accept_variant_is_idempotent(monkeypatch):
    session = _session()
    payload = {
        "version": 1,
        "items": [
            {"variant_id": "abc12345", "stem_md": "求 $2+2$ 的值。", "options": None,
             "answer_md": "$4$", "analysis_md": "直接相加得 4。", "qtype": "解答",
             "difficulty": 1, "kp_ids": [12],
             "self_check": {"status": "passed", "attempts": 1},
             "accepted_question_id": 128, "accepted_at": "2026-11-03T10:00:00+00:00"}
        ],
        "rejected": [],
        "stats": {"requested": 1, "passed": 1, "rejected": 0, "rounds": 1},
    }
    session.objects[(MistakeAnalysis, None)].similar_questions_json = payload
    existing = _question()
    existing.id = 128
    session.objects[(Question, 128)] = existing
    monkeypatch.setattr(
        svc.question_service, "create_generated_question",
        lambda *a, **k: pytest.fail("已入库的变式题不应重复建题"),
    )

    question, created = svc.accept_variant(
        session, owner=_Owner(), mistake_id=43, variant_id="abc12345"
    )

    assert created is False
    assert question.id == 128
    assert session.commits == 0


def test_accept_variant_unknown_id_404():
    session = _session()
    session.objects[(MistakeAnalysis, None)].similar_questions_json = {"version": 1, "items": []}

    with pytest.raises(NotFoundError, match="变式题不存在"):
        svc.accept_variant(session, owner=_Owner(), mistake_id=43, variant_id="nope")