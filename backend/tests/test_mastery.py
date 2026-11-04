"""S4-7 掌握度公式内核（方案 §6.6）：答对提升、答错下降、遗忘衰减、间隔变长。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.mastery_service import (
    INTERVAL_MAX_DAYS,
    INTERVAL_MIN_DAYS,
    K0,
    NEW_STATE,
    STABILITY_MAX,
    STABILITY_MIN,
    MasteryState,
    decayed_mastery,
    effective_k,
    next_mastery,
    next_stability,
    next_state,
    review_interval_days,
)

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def test_effective_k_divides_by_difficulty() -> None:
    assert K0 == 0.35
    assert effective_k(1) == pytest.approx(0.35)
    assert effective_k(3) == pytest.approx(0.1167, abs=1e-4)
    assert effective_k(5) == pytest.approx(0.07)


def test_effective_k_clamps_out_of_range_difficulty() -> None:
    # questions.difficulty 有 CHECK 1..5，但历史/脏数据不应让公式炸掉
    assert effective_k(0) == pytest.approx(0.35)
    assert effective_k(99) == pytest.approx(0.07)


def test_first_correct_raises_mastery_from_zero() -> None:
    """场景 1：答对提升（d=3 → K_eff=0.35/3）。"""
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    assert state.mastery == pytest.approx(0.117)
    assert state.attempts == 1
    assert state.correct_cnt == 1
    assert state.stability == pytest.approx(3.6)
    assert state.last_practice_at == NOW
    assert state.due_at > NOW


def test_second_correct_raises_again() -> None:
    state = next_state(NEW_STATE, s=1.0, difficulty=3, now=NOW)
    state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=1))
    assert state.mastery == pytest.approx(0.220)


def test_wrong_answer_lowers_mastery() -> None:
    """场景 2：答错下降。"""
    state = MasteryState(
        mastery=0.5,
        attempts=3,
        correct_cnt=2,
        stability=5.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    after = next_state(state, s=0.0, difficulty=3, now=NOW + timedelta(days=2))
    assert after.mastery == pytest.approx(0.442)
    assert after.stability == pytest.approx(2.5)


def test_mastery_never_goes_negative() -> None:
    state = MasteryState(
        mastery=0.05,
        attempts=1,
        correct_cnt=0,
        stability=2.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    assert next_state(state, s=0.0, difficulty=3, now=NOW).mastery == pytest.approx(0.044)
    assert next_mastery(0.0, 0.0, 0.35) == 0.0


def test_mastery_caps_at_one() -> None:
    assert next_mastery(1.0, 1.0, 0.35) == 1.0
    assert next_mastery(0.99, 1.0, 0.35) <= 1.0


def test_decay_after_ten_days() -> None:
    """场景 3：长时间不练衰减。"""
    assert decayed_mastery(0.8, 10.0, days=10.0) == pytest.approx(0.294)
    assert decayed_mastery(0.8, 10.0, days=0.0) == pytest.approx(0.8)
    assert decayed_mastery(0.8, 10.0, days=-5.0) == pytest.approx(0.8)


def test_stability_growth_and_shrink_bounds() -> None:
    assert next_stability(2.0, 1.0) == pytest.approx(3.6)
    assert next_stability(40.0, 1.0) == pytest.approx(STABILITY_MAX)
    assert next_stability(2.0, 0.0) == pytest.approx(1.0)
    assert next_stability(1.2, 0.0) == pytest.approx(STABILITY_MIN)


def test_half_correct_keeps_stability_and_does_not_count() -> None:
    state = MasteryState(
        mastery=0.4,
        attempts=2,
        correct_cnt=1,
        stability=5.0,
        last_practice_at=NOW,
        due_at=NOW,
    )
    after = next_state(state, s=0.5, difficulty=2, now=NOW)
    assert after.stability == pytest.approx(5.0)
    assert after.correct_cnt == 1
    # d=2 → K_eff=0.175；M = 0.4 + 0.175×(0.5−0.4) = 0.4175 → 0.418
    assert after.mastery == pytest.approx(0.418)


def test_interval_grows_with_repeated_success() -> None:
    """场景 4：连续答对间隔变长。"""
    state = NEW_STATE
    intervals = []
    for day in range(5):
        state = next_state(state, s=1.0, difficulty=3, now=NOW + timedelta(days=day))
        intervals.append((state.due_at - state.last_practice_at).days)
    assert state.mastery == pytest.approx(0.462)
    # 每步各自四舍五入：2 → 3.6 → 6.48 → 11.66 → 20.99 → 37.78
    assert state.stability == pytest.approx(37.78)
    assert intervals[0] == 1
    assert intervals[-1] == 17
    assert intervals == sorted(intervals)


def test_review_interval_clamps() -> None:
    assert review_interval_days(2.0, 0.0) == INTERVAL_MIN_DAYS
    assert review_interval_days(60.0, 1.0) == INTERVAL_MAX_DAYS
    assert review_interval_days(37.78, 0.462) == 17

# --------------------------------------------------------------------------
# DB 用例：全部用 FakeSession（真实 SQL 只验 WHERE，不连库）
# --------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

from app.models.enums import MistakeStatus  # noqa: E402
from app.models.mastery import Mastery  # noqa: E402
from app.models.mistake import Mistake  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import mastery_service  # noqa: E402
from app.utils.pagination import PageParams, SortParams  # noqa: E402


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class FakeMasterySession:
    """按「get → scalars 查已有行 → execute 事件流 / scalar 计数」的顺序喂结果。"""

    def __init__(
        self,
        *,
        objects: dict | None = None,
        existing: list[Mastery] | None = None,
        rows: list[tuple] | None = None,
        scalar_result: int | None = None,
    ) -> None:
        self.objects = objects or {}
        self.existing = existing or []
        self.rows = rows or []
        self.scalar_result = scalar_result
        self.added: list[Mastery] = []
        self.commits = 0
        self.statements: list[object] = []
        self._next_id = 700

    def get(self, entity, pk):  # noqa: ANN001, ANN201
        return self.objects.get((entity, pk))

    def scalars(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return iter(self.existing)

    def execute(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return _Rows(self.rows)

    def scalar(self, statement):  # noqa: ANN001, ANN201
        self.statements.append(statement)
        return self.scalar_result

    def add(self, instance) -> None:  # noqa: ANN001
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def _mastery_row(
    kp_id: int, *, mastery: float, attempts: int = 1, correct: int = 1
) -> Mastery:
    row = Mastery(
        user_id=50,
        kp_id=kp_id,
        mastery=Decimal(str(mastery)),
        attempts=attempts,
        correct_cnt=correct,
        stability=Decimal("3.60"),
        last_practice_at=NOW,
        due_at=NOW + timedelta(days=1),
    )
    row.id = 900 + kp_id
    return row


def test_record_attempts_creates_row_lazily() -> None:
    session = FakeMasterySession()
    rows = mastery_service.record_attempts(
        session, user_id=50, kp_ids=[3], s=1.0, difficulty=3, now=NOW
    )
    assert len(rows) == 1
    assert rows[0].kp_id == 3
    assert float(rows[0].mastery) == pytest.approx(0.117)
    assert rows[0].attempts == 1
    assert rows[0].correct_cnt == 1
    assert session.commits == 0  # 由调用方 commit


def test_record_attempts_updates_existing_row() -> None:
    existing = _mastery_row(3, mastery=0.5)
    session = FakeMasterySession(existing=[existing])
    mastery_service.record_attempts(
        session, user_id=50, kp_ids=[3], s=0.0, difficulty=3, now=NOW
    )
    assert float(existing.mastery) == pytest.approx(0.442)
    assert existing.attempts == 2
    assert existing.correct_cnt == 1
    assert session.added == []


def test_record_attempts_skips_empty_kp_list() -> None:
    session = FakeMasterySession()
    assert (
        mastery_service.record_attempts(
            session, user_id=50, kp_ids=[], s=1.0, difficulty=3, now=NOW
        )
        == []
    )


def test_recompute_user_replays_in_time_order() -> None:
    earlier = NOW - timedelta(days=3)
    later = NOW - timedelta(days=1)
    session = FakeMasterySession(
        rows=[
            # 故意乱序：先给晚的、再给早的，验证按 event_at 回放
            (1, MistakeStatus.MASTERED.value, later, 3, 7),
            (2, MistakeStatus.TODO.value, earlier, 3, 7),
        ],
        scalar_result=2,
    )
    result = mastery_service.recompute_user(session, user_id=50, now=NOW)
    assert result.events_replayed == 2
    assert result.rows_built == 1
    assert result.skipped_no_kp == 0
    assert session.commits == 1
    assert len(session.added) == 1
    # 先错(s=0，M 停在 0) 后对(s=1，M=0.117)
    assert float(session.added[0].mastery) == pytest.approx(0.117)
    assert session.added[0].attempts == 2


def test_recompute_user_counts_mistakes_without_kp() -> None:
    session = FakeMasterySession(rows=[], scalar_result=31)
    result = mastery_service.recompute_user(session, user_id=50, now=NOW)
    assert (result.events_replayed, result.rows_built, result.skipped_no_kp) == (0, 0, 31)


def test_recompute_user_is_idempotent() -> None:
    rows = [(1, MistakeStatus.CORRECTED.value, NOW, 3, 7)]
    first = FakeMasterySession(rows=rows, scalar_result=1)
    once = mastery_service.recompute_user(first, user_id=50, now=NOW)
    second = FakeMasterySession(rows=rows, scalar_result=1)
    twice = mastery_service.recompute_user(second, user_id=50, now=NOW)
    assert once == twice
    assert float(first.added[0].mastery) == pytest.approx(float(second.added[0].mastery))


def test_recompute_user_deletes_previous_rows() -> None:
    session = FakeMasterySession(
        rows=[(1, MistakeStatus.TODO.value, NOW, 2, 7)], scalar_result=1
    )
    mastery_service.recompute_user(session, user_id=50, now=NOW)
    sql = " ".join(str(stmt) for stmt in session.statements)
    assert "DELETE FROM mastery" in sql
    assert "mastery.user_id" in sql


def test_record_review_updates_mastery_for_question_kps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钩子：复习一次 → 掌握度按该题知识点各更新一次。"""
    from app.services import mistake_service

    session = FakeMasterySession(
        objects={}, rows=[(3,), (4,)]
    )
    mistake = _mistake()
    question = _question()
    session.objects[(Mistake, 12)] = mistake
    session.objects[(Question, 65)] = question
    captured: dict[str, object] = {}

    def fake_record(session_, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mastery_service, "record_attempts", fake_record)
    mistake_service.record_review(session, user_id=50, mistake_id=12, correct=True)
    assert captured["kp_ids"] == [3, 4]
    assert captured["s"] == 1.0
    assert captured["difficulty"] == 3
    assert captured["user_id"] == 50


def test_record_review_without_kp_does_not_touch_mastery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mistake_service

    session = FakeMasterySession(objects={}, rows=[])
    session.objects[(Mistake, 12)] = _mistake()
    session.objects[(Question, 65)] = _question()
    called: list[str] = []
    monkeypatch.setattr(
        mastery_service, "record_attempts", lambda *a, **k: called.append("x")
    )
    mistake_service.record_review(session, user_id=50, mistake_id=12, correct=False)
    assert called == []


def _mistake() -> Mistake:
    mistake = Mistake(
        user_id=50,
        question_id=65,
        status=MistakeStatus.TODO.value,
        correct_streak=0,
        my_answer_md="1",
        correct_answer_md="2",
    )
    mistake.id = 12
    mistake.created_at = NOW
    return mistake


def _question() -> Question:
    question = Question(
        subject_id=7,
        stem_md="题干",
        stem_hash="h" * 64,
        qtype="解答题",
        difficulty=3,
    )
    question.id = 65
    question.options_json = None
    question.answer_md = "2"
    return question


# --------------------------------------------------------------------------
# 接口层：401 / 403 / 参数透传
# --------------------------------------------------------------------------
def _user(role: str = "student") -> User:
    user = User(
        username=f"{role}_s47", nickname=role, grade="高二", role=role, password_hash="x"
    )
    user.id = 50 if role == "student" else 9
    return user


def _token(user: User) -> str:
    from app.core.security import create_access_token

    return create_access_token(user_id=user.id, role=user.role).token


def _client(user: User):  # noqa: ANN202
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app

    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else None

        def flush(self) -> None:
            return None

    app.dependency_overrides[get_db] = lambda: _Session()
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_token(user)}"})
    return client


def test_mastery_api_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/kp/mastery").status_code == 401
        assert client.post("/api/v1/kp/mastery/recompute").status_code == 401


def test_mastery_api_rejects_non_student() -> None:
    from app.main import app

    client = _client(_user("teacher"))
    try:
        assert client.get("/api/v1/kp/mastery").status_code == 403
        assert client.post("/api/v1/kp/mastery/recompute").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_recompute_api_forwards_user(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    captured: dict[str, int] = {}

    def fake_recompute(session, *, user_id):  # noqa: ANN001, ANN202
        captured["user_id"] = user_id
        return mastery_service.RecomputeResult(
            events_replayed=44, rows_built=13, skipped_no_kp=31
        )

    monkeypatch.setattr(mastery_service, "recompute_user", fake_recompute)
    client = _client(_user())
    try:
        resp = client.post("/api/v1/kp/mastery/recompute")
        assert resp.status_code == 200
        assert resp.json()["data"] == {
            "events_replayed": 44,
            "rows_built": 13,
            "skipped_no_kp": 31,
        }
        assert captured == {"user_id": 50}
    finally:
        app.dependency_overrides.clear()


def test_list_mastery_api_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app
    from app.schemas.kp import MasteryPage

    captured: dict[str, object] = {}

    def fake_list(session, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return MasteryPage(items=[], total=0, page=1, page_size=20)

    monkeypatch.setattr(mastery_service, "list_mastery", fake_list)
    client = _client(_user())
    try:
        resp = client.get("/api/v1/kp/mastery?subject_id=7&sort_by=due_at&order=asc")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 0
        assert captured["subject_id"] == 7
        assert captured["user_id"] == 50
        assert captured["sort"].sort_by == "due_at"
    finally:
        app.dependency_overrides.clear()
