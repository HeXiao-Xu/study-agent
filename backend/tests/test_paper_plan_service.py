"""S5-2 组卷服务：约束归一化、候选装载、生成/换题/保存/读取（FakeSession，不连库）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.paper import Paper
from app.schemas.common import PageData
from app.schemas.paper import PaperGenerateIn, PaperReplaceIn, PaperSaveIn, PaperSummaryOut
from app.services import paper_plan_service
from app.utils.pagination import PageParams

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=timezone.utc)


class FakeSession:
    """按调用顺序喂 execute 结果：服务查询顺序确定，顺序断言最直观。"""

    def __init__(self, *, results=None, paper=None) -> None:
        self.results = [list(rows) for rows in (results or [])]
        self.statements: list[object] = []
        self.added: list[object] = []
        self.committed = 0
        self.paper = paper

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        rows = self.results.pop(0) if self.results else []

        class _Result:
            def all(self):  # noqa: ANN201
                return rows

            def scalars(self):  # noqa: ANN201
                return rows

        return _Result()

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


def make_payload(**overrides) -> PaperGenerateIn:  # noqa: ANN003
    data = {
        "kp_ids": [101],
        "total_questions": 2,
        "qtype_ratio": {"单选": 1.0},
        "difficulty_dist": {2: 1.0},
        "total_score": 6,
        "exclude_recent_days": 14,
        "seed": 7,
    }
    data.update(overrides)
    return PaperGenerateIn(**data)


def candidate_rows():
    """load_candidates 第一条 SQL 的行：(id, qtype, difficulty, verified, origin, kp_id, weight)。"""
    return [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (502, "单选", 2, False, "upload", 101, Decimal("0.800000")),
        (503, "解答", 3, True, "textbook", 101, Decimal("1.000000")),
    ]


def test_build_constraints_filters_zero_qtype_and_normalizes_seed():
    payload = make_payload(qtype_ratio={"单选": 0.5, "多选": 0.0, "解答": 0.5})
    constraints = paper_plan_service.build_constraints(payload)
    assert dict(constraints.qtype_ratio) == {"单选": 0.5, "解答": 0.5}
    assert constraints.seed == 7
    assert constraints.total_score_target == 6


def test_build_constraints_generates_seed_in_range():
    constraints = paper_plan_service.build_constraints(make_payload(seed=None))
    assert 0 <= constraints.seed <= 2**31 - 1


def test_generate_in_rejects_all_zero_qtype_ratio():
    # 零权重在 schema 层就被挡住，build_constraints 里那层过滤只是防御
    with pytest.raises(ValidationError, match="请至少给一个题型设置占比"):
        make_payload(qtype_ratio={"单选": 0})


def test_generate_in_rejects_kp_weight_outside_selection():
    with pytest.raises(ValidationError, match="知识点权重只能设置已选中的知识点"):
        make_payload(kp_weights={999: 1.0})


def test_paper_save_in_rejects_duplicate_question_ids():
    from app.schemas.paper import PaperSaveIn

    with pytest.raises(ValidationError, match="重复"):
        PaperSaveIn(
            title="t",
            constraint=make_payload(),
            question_ids=[501, 501],
        )


def test_load_candidates_groups_multiple_kps_and_takes_latest_done():
    rows = [
        (501, "单选", 2, True, "exam", 101, Decimal("1.000000")),
        (501, "单选", 2, True, "exam", 102, Decimal("0.600000")),
    ]
    old = NOW - timedelta(days=40)
    fresh = NOW - timedelta(days=3)
    session = FakeSession(
        results=[
            rows,
            [(501, fresh, old)],
            [],
        ]
    )
    constraints = paper_plan_service.build_constraints(make_payload(kp_ids=[101, 102]))
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert [item.question_id for item in data.candidates] == [501]
    assert dict(data.candidates[0].kp_weights) == {101: 1.0, 102: 0.6}
    assert data.candidates[0].last_done_at == fresh
    assert data.mastery_by_kp == {}


def test_load_candidates_empty_rows_yields_empty_pool():
    session = FakeSession(results=[[], [], []])
    constraints = paper_plan_service.build_constraints(make_payload())
    data = paper_plan_service.load_candidates(
        session, constraints, user_id=50, now=NOW
    )
    assert data.candidates == ()
    assert data.mastery_by_kp == {}

def detail_rows():
    """明细 SQL 的行：id, subject_id, qtype, difficulty, stem_md, options_json, answer_md, analysis_md, verified, origin。"""
    return [
        (501, 7, "单选", 2, "题干 501", [{"key": "A", "text": "选项 A"}], "答案 501", None, True, "exam"),
        (502, 7, "单选", 2, "题干 502", [], "答案 502", None, False, "upload"),
        (503, 7, "解答", 3, "题干 503", [], "答案 503", "解析 503", True, "textbook"),
        (504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock"),
    ]


def full_row_set():
    """一次 generate 的查询顺序：候选 → 错题时间 → 掌握度 → 明细。"""
    return [
        candidate_rows(),
        [],
        [(101, Decimal("0.200"), Decimal("2.00"), NOW - timedelta(days=30))],
        detail_rows(),
    ]


def test_generate_preview_ok_returns_items_with_stem_and_answers():
    session = FakeSession(results=full_row_set())
    preview = paper_plan_service.generate_preview(
        session, make_payload(), user_id=50, now=NOW
    )
    assert preview.ok is True
    assert len(preview.items) == 2
    assert preview.total_score == 6
    assert preview.items[0].stem_md.startswith("题干")
    assert preview.items[0].answer_md.startswith("答案")
    assert preview.constraint.seed == 7
    assert preview.constraint.score_by_qtype == {"单选": 3, "多选": 4, "填空": 4, "解答": 8}


def test_generate_preview_reports_shortage_without_raising():
    session = FakeSession(results=full_row_set())
    preview = paper_plan_service.generate_preview(
        session, make_payload(total_questions=4, total_score=12), user_id=50, now=NOW
    )
    assert preview.ok is False
    codes = {violation.code for violation in preview.violations}
    assert "QTYPE_SHORTAGE" in codes


def test_generate_preview_no_candidates_reports_no_candidates():
    rows = candidate_rows()
    recent = [(501, NOW, NOW), (502, NOW, NOW), (503, NOW, NOW)]
    session = FakeSession(results=[rows, recent, [], []])
    preview = paper_plan_service.generate_preview(
        session, make_payload(kp_ids=[101]), user_id=50, now=NOW
    )
    assert preview.ok is False
    assert preview.items == []
    assert preview.violations[0].code == "NO_CANDIDATES"


def test_replace_item_prefers_same_qtype_and_difficulty_highest_score():
    rows = candidate_rows() + [(504, "单选", 2, True, "mock", 101, Decimal("1.000000"))]
    session = FakeSession(
        results=[rows, [], [], [(504, 7, "单选", 2, "题干 504", [], "答案 504", None, True, "mock")]]
    )
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is True
    assert result.item is not None
    # 504（verified=True, exam/mock 质量分高）应压过 502（未核对）
    assert result.item.question_id == 504


def test_replace_item_falls_back_to_same_qtype_any_difficulty():
    rows = candidate_rows() + [(505, "单选", 4, True, "exam", 101, Decimal("1.000000"))]
    details = [(505, 7, "单选", 4, "题干 505", [], "答案 505", None, True, "exam")]
    session = FakeSession(results=[rows, [], [], details])
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501, 502],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is True
    assert result.item is not None
    assert result.item.question_id == 505  # 同题型里没有 d2 了，退到 d4 的 505


def test_replace_item_returns_reason_when_pool_exhausted():
    session = FakeSession(results=[candidate_rows(), [], [], []])
    payload = PaperReplaceIn(
        **make_payload().model_dump(exclude={"seed"}),
        seed=7,
        selected_question_ids=[501, 502, 503],
        replace_question_id=501,
    )
    result = paper_plan_service.replace_item(session, payload, user_id=50, now=NOW)
    assert result.replaced is False
    assert result.item is None
    assert result.reason == "没有可替换的候选题"


def _stored_paper(**overrides):  # noqa: ANN003, ANN202
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
    for key, value in overrides.items():
        setattr(paper, key, value)
    return paper


def test_save_draft_recomputes_total_and_forces_draft():
    session = FakeSession(results=[[(501, "单选"), (502, "解答")]])
    payload = PaperSaveIn(
        title="期中卷", constraint=make_payload(total_score=11), question_ids=[501, 502]
    )
    saved = paper_plan_service.save_draft(session, payload, user_id=50)
    assert saved.total_score == 11  # 3 + 8，与入参 total_score 无关
    assert saved.status == "草稿"
    assert session.committed == 1
    assert session.added[0].question_ids == [501, 502]
    assert session.added[0].user_id == 50


def test_save_draft_rejects_missing_question_ids_and_writes_nothing():
    session = FakeSession(results=[[(501, "单选")]])
    payload = PaperSaveIn(title="t", constraint=make_payload(), question_ids=[501, 999])
    with pytest.raises(InvalidParamError, match="有题目已不存在"):
        paper_plan_service.save_draft(session, payload, user_id=50)
    assert session.committed == 0
    assert session.added == []


def test_get_paper_returns_items_in_stored_order_and_reports_missing():
    session = FakeSession(
        results=[
            [(501, 7, "单选", 2, "题干 501", [], "答案 501", None, True, "exam")],
            [(501, 101)],
        ],
        paper=_stored_paper(),
    )
    detail = paper_plan_service.get_paper(session, user_id=50, paper_id=7)
    assert [item.question_id for item in detail.items] == [501]
    assert detail.missing_question_ids == [502]
    assert detail.items[0].parts is None
    assert detail.items[0].score == 3
    assert detail.items[0].kp_ids == [101]
    assert detail.constraint_json == {"seed": 7}


def test_get_paper_forbids_other_users():
    session = FakeSession(paper=_stored_paper())
    with pytest.raises(ForbiddenError):
        paper_plan_service.get_paper(session, user_id=51, paper_id=7)


def test_get_paper_raises_not_found():
    session = FakeSession(paper=None)
    with pytest.raises(NotFoundError):
        paper_plan_service.get_paper(session, user_id=50, paper_id=99)


def test_list_papers_filters_owner_and_orders_by_saved_time(monkeypatch) -> None:
    session = FakeSession()
    captured: dict[str, object] = {}

    def fake_paginate(session_, stmt, params, *, item_model):  # noqa: ANN001, ANN202
        captured["sql"] = str(stmt)
        captured["params"] = params
        return PageData(
            items=[PaperSummaryOut.model_validate(_stored_paper())],
            total=1,
            page=params.page,
            page_size=params.page_size,
        )

    monkeypatch.setattr(paper_plan_service, "paginate_query", fake_paginate)
    data = paper_plan_service.list_papers(
        session, user_id=50, params=PageParams(page=1, page_size=10)
    )

    sql = str(captured["sql"])
    assert "papers.user_id" in sql
    assert "ORDER BY papers.created_at DESC, papers.id DESC" in sql
    assert data.items[0].question_count == 2
    assert data.total == 1
