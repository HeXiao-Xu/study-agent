"""S2-9/S4-5 知识点出入参（API.md §4、§4.5）。"""
from __future__ import annotations

from datetime import datetime

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


class GraphEdgeOut(BaseModel):
    """一条知识图谱关系边（API.md §4.5）；两端名称由服务层批查补齐。"""

    id: int
    src_kp_id: int
    src_name: str
    dst_kp_id: int
    dst_name: str
    relation: str
    weight: float | None = None
    source: str
    review_status: str
    reviewed_at: datetime | None = None
    created_at: datetime


class GraphEdgePage(BaseModel):
    items: list[GraphEdgeOut]
    total: int
    page: int
    page_size: int


class GraphStatsOut(BaseModel):
    subject_id: int | None = None
    nodes: int
    edges: int
    by_relation: dict[str, int]
    by_status: dict[str, int]
    last_built_at: datetime | None = None


class GraphBuildIn(BaseModel):
    subject_id: int = Field(ge=1)
    relations: list[str] | None = Field(default=None, max_length=4)
    limit: int | None = Field(default=None, ge=1, le=200)


class EdgeReviewIn(BaseModel):
    approve: bool


class EdgeReviewBatchIn(BaseModel):
    edge_ids: list[int] = Field(min_length=1, max_length=200)
    approve: bool


class EdgeReviewBatchOut(BaseModel):
    updated: int
    skipped: int


class GraphSnapshotNode(BaseModel):
    """快照节点：只给事实，颜色/大小由前端算（S4-6）。"""

    id: int
    name: str
    level: int
    parent_id: int | None = None
    exam_weight: float | None = None
    mistake_count: int = 0
    # S4-7：折算后的有效掌握度 M_t；无行（未评估）为 None，前端显示灰色
    mastery: float | None = None


class GraphSnapshotEdge(BaseModel):
    """快照边：只含 approved（S4-6）。"""

    src_kp_id: int
    dst_kp_id: int
    relation: str
    weight: float | None = None


class GraphSnapshotStats(BaseModel):
    nodes: int
    edges: int
    pending_edges: int
    by_relation: dict[str, int]


class GraphSubjectBrief(BaseModel):
    id: int
    name: str


class GraphSnapshotOut(BaseModel):
    subject: GraphSubjectBrief
    nodes: list[GraphSnapshotNode]
    edges: list[GraphSnapshotEdge]
    stats: GraphSnapshotStats


class GraphNeighborOut(BaseModel):
    kp_id: int
    name: str
    weight: float | None = None


class GraphNoteBrief(BaseModel):
    id: int
    title: str
    updated_at: datetime


class GraphMistakeBrief(BaseModel):
    id: int
    question_id: int
    status: str
    created_at: datetime
    stem: str


class GraphNodeDetailOut(BaseModel):
    id: int
    name: str
    level: int
    parent_id: int | None = None
    subject_id: int
    path: list[str]
    description: str | None = None
    exam_weight: float | None = None
    mistake_count: int = 0
    prerequisites: list[GraphNeighborOut] = Field(default_factory=list)
    successors: list[GraphNeighborOut] = Field(default_factory=list)
    related: list[GraphNeighborOut] = Field(default_factory=list)
    confusable: list[GraphNeighborOut] = Field(default_factory=list)
    notes: list[GraphNoteBrief] = Field(default_factory=list)
    mistakes: list[GraphMistakeBrief] = Field(default_factory=list)


class MasteryOut(BaseModel):
    """一条掌握度；`mastery` 是库存原值，`mastery_t` 是按当前时间折算的有效值。"""

    kp_id: int
    kp_name: str
    subject_id: int
    mastery: float
    mastery_t: float
    attempts: int
    correct_cnt: int
    stability: float
    last_practice_at: datetime | None = None
    due_at: datetime | None = None


class MasteryPage(BaseModel):
    items: list[MasteryOut]
    total: int
    page: int
    page_size: int


class MasteryRecomputeOut(BaseModel):
    events_replayed: int
    rows_built: int
    skipped_no_kp: int
