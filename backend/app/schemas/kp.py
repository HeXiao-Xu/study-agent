"""S2-9 知识点出入参（API.md §4）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    stage: str


class KpNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    parent_id: int | None
    name: str
    code: str
    level: int
    description: str | None
    exam_weight: float | None
    order_no: int
    children: list["KpNodeOut"] = Field(default_factory=list)


class KpTreeOut(BaseModel):
    subject: SubjectOut
    nodes: list[KpNodeOut]


class KpCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=30, description="学科 code")
    parent_id: int | None = Field(default=None, ge=1)
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    order_no: int = Field(default=0, ge=0)


class KpUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    order_no: int | None = Field(default=None, ge=0)
    parent_id: int | None = Field(default=None, ge=1)

class KpOrderIn(BaseModel):
    """拖拽落库：目标父级 + 完整目标兄弟顺序，可顺带移动一个节点。"""

    parent_id: int | None = Field(description="目标父节点；null 表示根级")
    ordered_ids: list[int] = Field(min_length=1, max_length=200)
    moved_id: int | None = Field(default=None, ge=1)
