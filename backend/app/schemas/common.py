"""统一成功响应壳（契约：docs/API.md §0）。

为什么泛型：data 的类型随接口不同，Envelope[T] 让 OpenAPI 文档
自动生成准确的出参结构，前端不用猜。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class HealthData(BaseModel):
    """GET /health 的出参（API.md §11）。"""

    status: str
    app: str
    version: str
    env: str


class Envelope(BaseModel, Generic[T]):
    """所有成功响应的统一壳：{code:0, message:"ok", trace_id, data}。"""

    code: int = 0
    message: str = "ok"
    trace_id: str
    data: T | None = None


class PageData(BaseModel, Generic[T]):
    """列表接口的统一分页 data（API.md §0，S2-4）。

    只暴露任务卡要求的 4 个字段；底层 fastapi-pagination 的 size/pages 不泄给前端。
    """

    items: list[T]
    total: int
    page: int
    page_size: int
