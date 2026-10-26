"""S2-4 统一分页/排序（spec §4）。

分页执行交给 fastapi-pagination（count 会剥掉 ORDER BY，limit/offset 由库生成），
但响应形状固定为 PageData 的 {items,total,page,page_size}，不把库的 size/pages 泄给前端。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from fastapi import Query
from fastapi_pagination import Params
from fastapi_pagination.ext.sqlalchemy import paginate as paginate_sa
from pydantic import BaseModel
from sqlalchemy import Select, asc, desc
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidParamError
from app.schemas.common import PageData

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True)
class SortParams:
    sort_by: str | None = None
    order: str = "desc"


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数（1–100）"
    ),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def sort_params(
    sort_by: str | None = Query(None, description="排序字段（白名单见各接口）"),
    order: Literal["asc", "desc"] = Query("desc", description="排序方向"),
) -> SortParams:
    return SortParams(sort_by=sort_by, order=order)


def paginate_query(
    session: Session,
    stmt: Select,
    params: PageParams,
    *,
    item_model: type[T],
) -> PageData[T]:
    page = paginate_sa(
        session,
        stmt,
        params=Params(page=params.page, size=params.page_size),
    )
    return PageData(
        items=[item_model.model_validate(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.size,
    )


def apply_sort(
    stmt: Select,
    *,
    sort_by: str | None,
    order: str,
    allowed: Mapping[str, Any],
    default_sort: str | None = None,
) -> Select:
    """白名单排序：allowed 的 key 才能出现在 ORDER BY，从结构上防注入。"""
    field = sort_by or default_sort
    if field is None:
        return stmt
    column = allowed.get(field)
    if column is None:
        options = ", ".join(sorted(allowed))
        raise InvalidParamError(f"不支持的排序字段：{field}（可选：{options}）")
    direction = order.lower()
    if direction not in {"asc", "desc"}:
        raise InvalidParamError("排序方向只能是 asc 或 desc")
    return stmt.order_by(asc(column) if direction == "asc" else desc(column))