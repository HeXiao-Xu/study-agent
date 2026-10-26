"""S2-7 任务注册表与 demo 任务。"""
from __future__ import annotations

import pytest

from app.tasks import registry
from app.tasks.demo import demo_sleep


def test_register_and_get_handler() -> None:
    def handler(session, payload):  # noqa: ANN001
        return {"ok": True}

    registry.register("unit.echo")(handler)
    assert registry.get_handler("unit.echo") is handler


def test_register_duplicate_name_raises() -> None:
    def handler(session, payload):  # noqa: ANN001
        return None

    registry.register("unit.dup")(handler)
    with pytest.raises(ValueError):
        registry.register("unit.dup")(handler)


def test_all_suffix_is_rejected() -> None:
    with pytest.raises(ValueError):
        registry.register("unit.all")


def test_demo_sleep_returns_slept_seconds() -> None:
    assert demo_sleep(None, {"seconds": 0}) == {"slept": 0}  # type: ignore[arg-type]


def test_demo_sleep_fail_raises() -> None:
    with pytest.raises(RuntimeError):
        demo_sleep(None, {"seconds": 0, "fail": True})  # type: ignore[arg-type]