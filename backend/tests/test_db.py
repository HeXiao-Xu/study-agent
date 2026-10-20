"""S1-3/S1-4 数据库基座回归：Windows 下必须带连接超时，避免 IPv6 卡死。"""
from __future__ import annotations

import pytest

from app.core import db


def test_engine_sets_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    monkeypatch.setattr(db, "_engine", None)

    db.get_engine()

    assert captured["connect_args"] == {"connect_timeout": 5}