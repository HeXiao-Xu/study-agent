"""S2-4 分页参数与响应形状接口测试（spec §6.2）。"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.context import get_trace_id
from app.core.exceptions import install_exception_handlers
from app.schemas.common import Envelope, PageData
from app.utils.pagination import (
    PageParams,
    SortParams,
    apply_sort,
    page_params,
    paginate_query,
    sort_params,
)


class _Base(DeclarativeBase):
    pass


class Demo(_Base):
    __tablename__ = "pagination_api_demo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class DemoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


SORT_FIELDS = {"id": Demo.id, "name": Demo.name}


@pytest.fixture
def session() -> Iterator[Session]:
    # TestClient 在另一个线程里跑路由；StaticPool 保证它和夹具共用同一个内存库连接
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Demo(name=f"n{index}") for index in range(5)])
        db.commit()
        yield db


def _make_app(db: Session) -> FastAPI:
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.dependency_overrides[get_db] = lambda: db

    @test_app.get("/demos", response_model=Envelope[PageData[DemoOut]])
    def list_demos(
        params: PageParams = Depends(page_params),
        sorting: SortParams = Depends(sort_params),
        session: Session = Depends(get_db),
    ) -> Envelope[PageData[DemoOut]]:
        stmt = apply_sort(
            select(Demo),
            sort_by=sorting.sort_by,
            order=sorting.order,
            allowed=SORT_FIELDS,
            default_sort="id",
        )
        return Envelope(
            trace_id=get_trace_id(),
            data=paginate_query(session, stmt, params, item_model=DemoOut),
        )

    return test_app


def _client(db: Session) -> TestClient:
    return TestClient(_make_app(db))


def test_default_request_returns_four_field_page(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data) == {"items", "total", "page", "page_size"}
    assert (data["total"], data["page"], data["page_size"]) == (5, 1, 20)


def test_second_page_returns_expected_items(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page": 2, "page_size": 2})
    data = resp.json()["data"]
    assert [item["id"] for item in data["items"]] == [3, 2]  # 默认 id desc


def test_page_zero_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page": 0})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_page_size_over_limit_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"page_size": 101})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_unknown_sort_field_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"sort_by": "password"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200
    assert "不支持的排序字段" in resp.json()["message"]


def test_invalid_order_is_rejected(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"order": "sideways"})
    assert resp.status_code == 422
    assert resp.json()["code"] == 42200


def test_sort_by_name_ascending(session: Session) -> None:
    with _client(session) as client:
        resp = client.get("/demos", params={"sort_by": "name", "order": "asc"})
    names = [item["name"] for item in resp.json()["data"]["items"]]
    assert names == ["n0", "n1", "n2", "n3", "n4"]


def test_total_is_stable_across_pages(session: Session) -> None:
    with _client(session) as client:
        first = client.get("/demos", params={"page": 1, "page_size": 2}).json()["data"]
        second = client.get("/demos", params={"page": 2, "page_size": 2}).json()["data"]
    assert first["total"] == second["total"] == 5