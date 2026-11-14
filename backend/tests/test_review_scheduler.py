"""S5-5 调度器：advisory lock、逐用户提交、单用户失败隔离。"""
from __future__ import annotations

from app import scheduler
from app.schemas.review import ReviewTodayOut


class FakeSession:
    def __init__(self, *, locked=True, user_ids=None):
        self.locked = locked
        self.user_ids = user_ids or []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def scalar(self, stmt, params=None):
        self.calls.append(("scalar", str(stmt)))
        return self.locked

    def scalars(self, stmt):
        self.calls.append(("scalars", str(stmt)))
        return list(self.user_ids)

    def execute(self, stmt, params=None):
        self.calls.append(("execute", str(stmt)))
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = FakeSession(locked=True, user_ids=[50, 51])
        self.sessions.append(session)
        return session


def _empty_today() -> ReviewTodayOut:
    return ReviewTodayOut(
        date="2026-11-14",
        timezone="Asia/Shanghai",
        items=[],
        item_count=0,
        total_minutes=0,
        cap_minutes=35,
        truncated_count=None,
    )


def test_generate_daily_skips_when_lock_not_acquired():
    factory = lambda: FakeSession(locked=False, user_ids=[50])
    result = scheduler.generate_daily(session_factory=factory)
    assert result["users"] == 0
    assert result["items"] == 0
    assert result["failed"] == 0


def test_generate_daily_isolates_user_failures(monkeypatch):
    factory = FakeFactory()
    calls = []

    def fake_refresh(session, *, user_id, now=None):
        calls.append(user_id)
        if user_id == 51:
            raise RuntimeError("boom")
        return _empty_today()

    monkeypatch.setattr(scheduler.review_service, "refresh_user", fake_refresh)
    result = scheduler.generate_daily(session_factory=factory)
    assert result == {"users": 2, "items": 0, "failed": 1}
    assert calls == [50, 51]
    assert factory.sessions[2].rollbacks == 1