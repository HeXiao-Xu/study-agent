"""S2-4 分页与排序单元测试（spec §6.1）。

用 SQLite 内存库真执行 SQL：分页件没有业务逻辑，只有真实执行才能证明
count 与 limit/offset 的配合正确；SQLite 是进程内库，不违反"测试不连外部服务"。
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.core.exceptions import InvalidParamError
from app.schemas.common import PageData
from app.utils.pagination import PageParams, apply_sort, page_params, paginate_query


class _Base(DeclarativeBase):
    pass


class Demo(_Base):
    __tablename__ = "pagination_demo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class DemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


@pytest.fixture
def session() -> Session:
    # 内存库默认每个连接一份；StaticPool 让 Session 始终复用同一连接（TestClient 跨线程也成立）
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Demo(name=f"n{index}") for index in range(5)])
        db.commit()
        yield db


def _ids(page: PageData[DemoOut]) -> list[int]:
    return [item.id for item in page.items]


def test_page_params_defaults() -> None:
    params = PageParams()
    assert (params.page, params.page_size) == (1, 20)


def test_page_params_dependency_builds_dataclass() -> None:
    assert page_params(2, 10) == PageParams(page=2, page_size=10)


def test_paginate_first_page(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=1, page_size=2), item_model=DemoOut)
    assert _ids(page) == [1, 2]
    assert (page.total, page.page, page.page_size) == (5, 1, 2)


def test_paginate_second_page(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=2, page_size=2), item_model=DemoOut)
    assert _ids(page) == [3, 4]
    assert page.total == 5


def test_paginate_beyond_last_page_returns_empty(session: Session) -> None:
    stmt = select(Demo).order_by(Demo.id)
    page = paginate_query(session, stmt, PageParams(page=9, page_size=2), item_model=DemoOut)
    assert page.items == []
    assert page.total == 5


def test_paginate_converts_items_to_output_model(session: Session) -> None:
    page = paginate_query(
        session, select(Demo).order_by(Demo.id), PageParams(), item_model=DemoOut
    )
    assert all(isinstance(item, DemoOut) for item in page.items)


def test_apply_sort_ascending(session: Session) -> None:
    stmt = apply_sort(select(Demo), sort_by="id", order="asc", allowed={"id": Demo.id})
    assert [item.id for item in session.scalars(stmt).all()] == [1, 2, 3, 4, 5]


def test_apply_sort_descending(session: Session) -> None:
    stmt = apply_sort(
        select(Demo), sort_by="name", order="desc", allowed={"name": Demo.name}
    )
    assert [item.name for item in session.scalars(stmt).all()] == ["n4", "n3", "n2", "n1", "n0"]


def test_apply_sort_rejects_unknown_field() -> None:
    with pytest.raises(InvalidParamError) as excinfo:
        apply_sort(select(Demo), sort_by="password", order="asc", allowed={"id": Demo.id})
    assert excinfo.value.code == 42200
    assert "不支持的排序字段" in excinfo.value.message


def test_apply_sort_rejects_unknown_order() -> None:
    with pytest.raises(InvalidParamError):
        apply_sort(select(Demo), sort_by="id", order="sideways", allowed={"id": Demo.id})


def test_apply_sort_without_sort_or_default_keeps_stmt() -> None:
    stmt = apply_sort(select(Demo), sort_by=None, order="desc", allowed={"id": Demo.id})
    assert "ORDER BY" not in str(stmt)


def test_apply_sort_uses_default_sort() -> None:
    stmt = apply_sort(
        select(Demo), sort_by=None, order="asc", allowed={"id": Demo.id}, default_sort="id"
    )
    assert "ORDER BY" in str(stmt)