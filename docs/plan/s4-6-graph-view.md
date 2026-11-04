# S4-6 图谱可视化前端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `/graph` 图谱可视化页：力导向图（ECharts）、点节点看详情侧栏、模块折叠、搜索定位、>300 节点降级子图。

**Architecture:** 后端只加 2 个只读接口（`/kp/graph/snapshot` 一次给全图、`/kp/graph/nodes/{id}` 按需给详情），无数据库变更；前端把「取数 → 可见集合 → ECharts option」三层拆开，纯函数放 `useGraphData.ts` 便于单测，`Graph.vue` 只管画布与交互。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（只读查询）、Pydantic v2；Vue 3 + TS + Element Plus + **echarts 6.1.0（按需引入）**；Vitest。

**Spec:** `docs/spec/s4-6-graph-view.md`

## Global Constraints

- 工作目录：后端命令在 `study-agent/backend` 下执行，前端在 `study-agent/web` 下执行；Python 解释器统一 `../.venv/Scripts/python.exe`。
- 后端：路由 ≤30 行、一个用例一个事务、业务错误抛 `AppError` 子类（`NotFoundError` → 404/40400）、所有函数带类型标注。
- 后端：**只读，不 `commit`**；禁止 N+1（一次 SQL 查完再内存拼装）。
- 只有 **approved** 的边对外可见；pending 只允许出现在 `stats.pending_edges` 计数里。
- 笔记/错题按 `user_id` 隔离；老师/管理员也是本人口径。
- 前端：API 只经 `src/api/`；组件不重复 try-catch 弹窗（`http.ts` 已统一弹错）。
- 前端：禁止 `any`（vue-tsc 严格模式）；新代码照 `KnowledgeView.vue`/`GraphReview.vue` 的样式。
- 不造假数据：描述为空显示「暂无描述」，笔记为空显示「暂无关联笔记」。
- 每次提交前跑：后端 `pytest -q`、前端 `npm run test:run -- --pool=threads` 与 `npm run build`。
- 提交信息 Conventional Commits 带任务号（`feat(s4-6): ...`）；用户负责 `git push`。

---

### Task 1: 后端快照接口（API 契约 + schema + service + route）

**Files:**
- Modify: `docs/API.md:§4.5`（新增 `/kp/graph/snapshot` 与 `/kp/graph/nodes/{kp_id}` 两条，先改契约）
- Modify: `backend/app/schemas/kp.py`（文件末尾追加 8 个模型）
- Modify: `backend/app/services/graph_service.py`（追加 `_mistake_counts`、`snapshot`）
- Modify: `backend/app/api/v1/kp.py`（追加 1 条路由与 import）
- Create: `backend/tests/test_graph_snapshot.py`

**Interfaces:**
- Produces:
  - `graph_service.snapshot(session: Session, *, subject_id: int, user_id: int) -> GraphSnapshotOut`
  - `graph_service._mistake_counts(session: Session, *, user_id: int, kp_ids: Sequence[int]) -> dict[int, int]`
  - schema 模型：`GraphSnapshotNode`、`GraphSnapshotEdge`、`GraphSnapshotStats`、`GraphSubjectBrief`、`GraphSnapshotOut`（字段见 Task 1 Step 4）
  - HTTP：`GET /api/v1/kp/graph/snapshot?subject_id=7` → `Envelope[GraphSnapshotOut]`，登录即可访问（学生也能）

- [ ] **Step 1: 先补 API.md 契约**

在 `docs/API.md` §4.5 的 `GET /api/v1/kp/graph/stats` 之前插入：

```markdown
#### GET /api/v1/kp/graph/snapshot
- 权限：任意登录用户（图谱结构非隐私数据；学生也能看）
- 入参：`subject_id`（必填，int ≥1）
- 出参：`Envelope[GraphSnapshotOut]`，`{"subject": {"id": 7, "name": "高中数学"}, "nodes": [{"id": 12, "name": "导数与函数的单调性", "level": 3, "parent_id": 9, "exam_weight": 0.8, "mistake_count": 2}], "edges": [{"src_kp_id": 3, "dst_kp_id": 12, "relation": "prerequisite", "weight": 0.95}], "stats": {"nodes": 108, "edges": 264, "pending_edges": 50, "by_relation": {"contains": 107, "prerequisite": 114, "related": 4, "confusable": 39}}}`
- 备注：`edges` **只含 `review_status='approved'`**；`stats.pending_edges` 只给计数（老师视角提示待审核量），不返回 pending 边；`by_relation` 四个键恒在（无该关系时为 0）；`mistake_count` 口径 = `mistakes(user_id=当前用户) → questions → question_kps` 去重计数，老师也是本人口径
- 错误：`401/40100`、`404/40400`（学科不存在）、`422/42200`

#### GET /api/v1/kp/graph/nodes/{kp_id}
- 权限：任意登录用户
- 出参：`Envelope[GraphNodeDetailOut]`，见 `docs/spec/s4-6-graph-view.md` §3.1（含 `path` 面包屑、四类 approved 邻居、本人笔记与错题）
- 备注：`notes` 只取 `note_kps.confirmed=true` + `notes.deleted_at IS NULL` + 本人，最多 20 条；`mistakes` 按 `created_at DESC` 最多 20 条，`stem` 为题干前 60 字；四类邻居都只取 approved，`contains` 不出现在侧栏（父链由 `path` 表达）
- 错误：`401/40100`、`404/40400`（知识点不存在）、`422/42200`
```

- [ ] **Step 2: 写失败的测试（快照服务 + 接口）**

创建 `backend/tests/test_graph_snapshot.py`：

```python
"""S4-6 图谱快照：只出 approved 边、pending 只计数、错题按用户、接口权限。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.security import create_access_token
from app.main import app
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.subject import Subject
from app.models.user import User
from app.schemas.kp import GraphSnapshotOut
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _node(kp_id: int, name: str, *, level: int = 3, parent_id: int | None = 1) -> KnowledgePoint:
    node = KnowledgePoint(
        subject_id=7,
        name=name,
        level=level,
        parent_id=parent_id,
        exam_weight=Decimal("0.800"),
    )
    node.id = kp_id
    return node


def _edge(edge_id: int, src: int, dst: int, relation: str, status: str) -> KnowledgeEdge:
    edge = KnowledgeEdge(
        src_kp_id=src,
        dst_kp_id=dst,
        relation=relation,
        source="ai",
        review_status=status,
        weight=Decimal("0.900"),
        reviewed_at=None if status == "pending" else NOW,
    )
    edge.id = edge_id
    return edge


class FakeSnapshotSession:
    """按 SQL 里的表名分派：scalars 分 nodes/edges，execute 只服务错题计数。"""

    def __init__(
        self,
        *,
        subject: Subject | None,
        nodes: list[KnowledgePoint],
        edges: list[KnowledgeEdge],
        mistake_rows: list[tuple[int, int]] | None = None,
        pending: int = 0,
    ) -> None:
        self.subject = subject
        self.nodes = nodes
        self.edges = edges
        self.mistake_rows = mistake_rows or []
        self.pending = pending
        self.committed = 0

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.subject if model is Subject else None

    def scalars(self, statement):  # noqa: ANN001, ANN201
        sql = str(statement)
        return iter(self.edges) if "knowledge_edges" in sql else iter(self.nodes)

    def execute(self, statement):  # noqa: ANN001, ANN201
        rows = self.mistake_rows

        class _Rows:
            def all(self):
                return rows

        return _Rows()

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.pending

    def commit(self) -> None:
        self.committed += 1


def _session(**kwargs) -> FakeSnapshotSession:  # noqa: ANN003
    subject = kwargs.pop("subject", Subject(name="高中数学", code="math"))
    subject.id = 7
    kwargs.setdefault("nodes", [_node(1, "函数", level=1, parent_id=None), _node(2, "导数")])
    return FakeSnapshotSession(subject=subject, **kwargs)


def test_snapshot_keeps_only_approved_edges() -> None:
    session = _session(
        edges=[
            _edge(1, 1, 2, "prerequisite", "approved"),
            _edge(2, 1, 2, "related", "pending"),
            _edge(3, 1, 2, "confusable", "rejected"),
        ]
    )
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert [(e.relation, e.src_kp_id, e.dst_kp_id) for e in out.edges] == [("prerequisite", 1, 2)]
    assert out.stats.edges == 1


def test_snapshot_counts_pending_separately() -> None:
    session = _session(edges=[_edge(1, 1, 2, "prerequisite", "approved")], pending=50)
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert out.stats.pending_edges == 50


def test_snapshot_by_relation_always_has_four_keys() -> None:
    session = _session(edges=[_edge(1, 1, 2, "prerequisite", "approved")])
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    assert out.stats.by_relation == {
        "contains": 0,
        "prerequisite": 1,
        "related": 0,
        "confusable": 0,
    }


def test_snapshot_fills_mistake_count_by_kp() -> None:
    session = _session(mistake_rows=[(2, 3)])
    out = graph_service.snapshot(session, subject_id=7, user_id=50)
    counts = {node.id: node.mistake_count for node in out.nodes}
    assert counts == {1: 0, 2: 3}


def test_snapshot_unknown_subject_raises_not_found() -> None:
    session = FakeSnapshotSession(subject=None, nodes=[], edges=[])
    with pytest.raises(NotFoundError):
        graph_service.snapshot(session, subject_id=99, user_id=50)


def test_snapshot_does_not_commit() -> None:
    session = _session()
    graph_service.snapshot(session, subject_id=7, user_id=50)
    assert session.committed == 0


class FakeSession:
    """接口层的假会话：get_current_user 只查 User。"""

    def __init__(self, user: User) -> None:
        self.user = user

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.user if model is User else None

    def scalar(self, statement):  # noqa: ANN001, ANN201
        return self.user if "users" in str(statement) else 0

    def flush(self) -> None:
        return None


def _user(role: str) -> User:
    user = User(username=f"{role}_s46", nickname=role, grade="高二", role=role, password_hash="x")
    user.id = 50 if role == "student" else 9
    return user


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, role=user.role).token
    return {"Authorization": f"Bearer {token}"}


def _snapshot_out() -> GraphSnapshotOut:
    from app.schemas.kp import GraphSnapshotEdge, GraphSnapshotNode, GraphSnapshotStats, GraphSubjectBrief

    return GraphSnapshotOut(
        subject=GraphSubjectBrief(id=7, name="高中数学"),
        nodes=[GraphSnapshotNode(id=2, name="导数", level=3, parent_id=1, exam_weight=0.8, mistake_count=1)],
        edges=[GraphSnapshotEdge(src_kp_id=1, dst_kp_id=2, relation="prerequisite", weight=0.9)],
        stats=GraphSnapshotStats(nodes=2, edges=1, pending_edges=50, by_relation={"contains": 0, "prerequisite": 1, "related": 0, "confusable": 0}),
    )


def test_snapshot_api_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/kp/graph/snapshot").status_code == 401


def test_snapshot_api_allows_student(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    student = _user("student")
    app.dependency_overrides[get_db] = lambda: FakeSession(student)
    monkeypatch.setattr(graph_service, "snapshot", lambda session, **kw: _snapshot_out())
    resp = client.get("/api/v1/kp/graph/snapshot?subject_id=7", headers=_headers(student))
    assert resp.status_code == 200
    assert resp.json()["data"]["stats"]["pending_edges"] == 50
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_snapshot.py -q`
Expected: FAIL —— `AttributeError: module 'app.services.graph_service' has no attribute 'snapshot'`，且 `ImportError`（schema 不存在）。

- [ ] **Step 4: 追加 schema**

在 `backend/app/schemas/kp.py` 末尾追加（`Field` 若未 import，在文件顶部 `from pydantic import BaseModel, Field` 补上）：

```python
class GraphSnapshotNode(BaseModel):
    """快照节点：只给事实，颜色/大小由前端算（S4-6）。"""

    id: int
    name: str
    level: int
    parent_id: int | None = None
    exam_weight: float | None = None
    mistake_count: int = 0


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
```

- [ ] **Step 5: 追加 service 用例**

在 `backend/app/services/graph_service.py` 的 `enqueue_build` **之前**插入：

```python
def _mistake_counts(
    session: Session, *, user_id: int, kp_ids: Sequence[int]
) -> dict[int, int]:
    """当前用户在每个知识点下的错题数（去重题目，不看 status）。"""
    from app.models.mistake import Mistake
    from app.models.question_kp import QuestionKp

    if not kp_ids:
        return {}
    rows = session.execute(
        select(QuestionKp.kp_id, func.count(func.distinct(Mistake.id)))
        .join(Mistake, Mistake.question_id == QuestionKp.question_id)
        .where(Mistake.user_id == user_id)
        .where(QuestionKp.kp_id.in_(list(kp_ids)))
        .group_by(QuestionKp.kp_id)
    ).all()
    return {int(kp_id): int(count) for kp_id, count in rows}


def snapshot(session: Session, *, subject_id: int, user_id: int) -> Any:
    """一次给全图：节点 + 已审核边 + 统计（S4-6，只读）。"""
    from app.models.subject import Subject
    from app.schemas.kp import (
        GraphSnapshotEdge,
        GraphSnapshotNode,
        GraphSnapshotOut,
        GraphSnapshotStats,
        GraphSubjectBrief,
    )

    subject = session.get(Subject, subject_id)
    if subject is None:
        raise NotFoundError("学科不存在")
    nodes = _load_nodes(session, subject_id)
    node_ids = [node.id for node in nodes]
    counts = _mistake_counts(session, user_id=user_id, kp_ids=node_ids)
    edges = (
        list(
            session.scalars(
                select(KnowledgeEdge)
                .where(KnowledgeEdge.review_status == EdgeReviewStatus.APPROVED)
                .where(KnowledgeEdge.src_kp_id.in_(node_ids))
                .order_by(KnowledgeEdge.id)
            )
        )
        if node_ids
        else []
    )
    pending = (
        int(
            session.scalar(
                select(func.count())
                .select_from(KnowledgeEdge)
                .where(KnowledgeEdge.review_status == EdgeReviewStatus.PENDING)
                .where(KnowledgeEdge.src_kp_id.in_(node_ids))
            )
            or 0
        )
        if node_ids
        else 0
    )
    by_relation: dict[str, int] = {relation: 0 for relation in RELATIONS}
    for edge in edges:
        by_relation[edge.relation] = by_relation.get(edge.relation, 0) + 1
    return GraphSnapshotOut(
        subject=GraphSubjectBrief(id=subject.id, name=subject.name),
        nodes=[
            GraphSnapshotNode(
                id=node.id,
                name=node.name,
                level=node.level,
                parent_id=node.parent_id,
                exam_weight=(
                    float(node.exam_weight) if node.exam_weight is not None else None
                ),
                mistake_count=counts.get(node.id, 0),
            )
            for node in nodes
        ],
        edges=[
            GraphSnapshotEdge(
                src_kp_id=edge.src_kp_id,
                dst_kp_id=edge.dst_kp_id,
                relation=edge.relation,
                weight=float(edge.weight) if edge.weight is not None else None,
            )
            for edge in edges
        ],
        stats=GraphSnapshotStats(
            nodes=len(nodes),
            edges=len(edges),
            pending_edges=pending,
            by_relation=by_relation,
        ),
    )
```

同时把文件顶部 `from app.core.exceptions import InvalidParamError` 改成：

```python
from app.core.exceptions import InvalidParamError, NotFoundError
```

- [ ] **Step 6: 追加路由**

`backend/app/api/v1/kp.py`：schema import 块补 `GraphNodeDetailOut`、`GraphSnapshotOut`（`GraphNodeDetailOut` 在 Task 2 用到，先一起 import 会在 Task 1 报未使用吗？不会——本步只加 `GraphSnapshotOut`，Task 2 再加 `GraphNodeDetailOut`）。

在 `graph_stats` 路由**之前**插入：

```python
@router.get(
    "/graph/snapshot", response_model=Envelope[GraphSnapshotOut], summary="图谱快照"
)
def graph_snapshot(
    subject_id: int = Query(..., ge=1, description="学科 id"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[GraphSnapshotOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=graph_service.snapshot(
            session, subject_id=subject_id, user_id=current_user.id
        ),
    )
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_snapshot.py -q`
Expected: `10 passed`

- [ ] **Step 8: 全量回归 + 提交**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent && git add backend/app/schemas/kp.py backend/app/services/graph_service.py backend/app/api/v1/kp.py backend/tests/test_graph_snapshot.py docs/API.md
git commit -m "feat(s4-6): 后端图谱快照接口（只出 approved 边）"
```

Expected: 后端全绿（当前基线 1142 → 1152）。

---

### Task 2: 后端节点详情接口

**Files:**
- Modify: `backend/app/services/graph_service.py`（追加 `_ancestor_path`、`_approved_neighbors`、`node_detail`）
- Modify: `backend/app/api/v1/kp.py`（追加 1 条路由 + import `GraphNodeDetailOut`）
- Create: `backend/tests/test_graph_node_detail.py`

**Interfaces:**
- Consumes: Task 1 的 `_mistake_counts`；schema `GraphNodeDetailOut/GraphNeighborOut/GraphNoteBrief/GraphMistakeBrief`
- Produces: `graph_service.node_detail(session: Session, *, kp_id: int, user_id: int) -> GraphNodeDetailOut`；`GET /api/v1/kp/graph/nodes/{kp_id}`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_graph_node_detail.py`：

```python
"""S4-6 节点详情：面包屑、四类邻居只取 approved、笔记/错题按本人过滤。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import NotFoundError
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def _node(kp_id: int, name: str, *, level: int, parent_id: int | None) -> KnowledgePoint:
    node = KnowledgePoint(
        subject_id=7,
        name=name,
        level=level,
        parent_id=parent_id,
        description=None,
        exam_weight=Decimal("0.800"),
    )
    node.id = kp_id
    return node


def _edge(edge_id: int, src: int, dst: int, relation: str, status: str) -> KnowledgeEdge:
    edge = KnowledgeEdge(
        src_kp_id=src,
        dst_kp_id=dst,
        relation=relation,
        source="ai",
        review_status=status,
        weight=Decimal("0.900"),
        reviewed_at=None if status == "pending" else NOW,
    )
    edge.id = edge_id
    return edge


class FakeDetailSession:
    """get() 服务节点与祖先；scalars 服务邻居边；execute 分派名称/笔记/错题。"""

    def __init__(self, *, nodes, edges, notes=(), mistakes=(), mistake_rows=()) -> None:
        self.nodes = {node.id: node for node in nodes}
        self.edges = edges
        self.notes = list(notes)
        self.mistakes = list(mistakes)
        self.mistake_rows = list(mistake_rows)
        self.committed = 0

    def get(self, model, pk):  # noqa: ANN001, ANN201
        return self.nodes.get(pk) if model is KnowledgePoint else None

    def scalars(self, statement):  # noqa: ANN001, ANN201
        return iter(self.edges)

    def execute(self, statement):  # noqa: ANN001, ANN201
        sql = str(statement)
        if "note_kps" in sql:
            rows = self.notes
        elif "mistakes" in sql:
            rows = self.mistakes
        else:
            rows = [
                (node.id, node.name)
                for node in self.nodes.values()
                if node.level >= 3
            ]

        class _Rows:
            def all(self):
                return rows

        return _Rows()

    def commit(self) -> None:
        self.committed += 1


def _triangle():
    root = _node(1, "高中数学", level=1, parent_id=None)
    chapter = _node(2, "导数及其应用", level=2, parent_id=1)
    target = _node(3, "导数与函数的单调性", level=3, parent_id=2)
    other = _node(4, "函数的单调性", level=3, parent_id=1)
    successor = _node(5, "函数的极值与最值", level=3, parent_id=2)
    return [root, chapter, target, other, successor]


def test_node_detail_builds_path_from_root() -> None:
    nodes = _triangle()
    session = FakeDetailSession(nodes=nodes, edges=[])
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.path == ["高中数学", "导数及其应用", "导数与函数的单调性"]
    assert out.description is None
    assert out.prerequisites == [] and out.notes == [] and out.mistakes == []


def test_node_detail_splits_prerequisites_and_successors() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes,
        edges=[
            _edge(1, 4, 3, "prerequisite", "approved"),
            _edge(2, 3, 5, "prerequisite", "approved"),
        ],
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert [n.kp_id for n in out.prerequisites] == [4]
    assert [n.name for n in out.prerequisites] == ["函数的单调性"]
    assert [n.kp_id for n in out.successors] == [5]


def test_node_detail_ignores_non_approved_edges() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes, edges=[_edge(1, 4, 3, "prerequisite", "pending")]
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.prerequisites == []


def test_node_detail_ignores_contains_edges() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes, edges=[_edge(1, 2, 3, "contains", "approved")]
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert out.prerequisites == [] and out.successors == [] and out.related == []


def test_node_detail_returns_notes_and_mistakes_rows() -> None:
    nodes = _triangle()
    session = FakeDetailSession(
        nodes=nodes,
        edges=[],
        notes=[(7, "导数单调性整理", NOW)],
        mistakes=[(9, 33, "待订正", NOW, "已知函数 f(x)=…")],
        mistake_rows=[(3, 1)],
    )
    out = graph_service.node_detail(session, kp_id=3, user_id=50)
    assert [(n.id, n.title) for n in out.notes] == [(7, "导数单调性整理")]
    assert [(m.id, m.question_id, m.stem) for m in out.mistakes] == [
        (9, 33, "已知函数 f(x)=…")
    ]
    assert out.mistake_count == 1


def test_node_detail_unknown_kp_raises_not_found() -> None:
    session = FakeDetailSession(nodes=_triangle(), edges=[])
    with pytest.raises(NotFoundError):
        graph_service.node_detail(session, kp_id=999, user_id=50)


def test_node_detail_does_not_commit() -> None:
    session = FakeDetailSession(nodes=_triangle(), edges=[])
    graph_service.node_detail(session, kp_id=3, user_id=50)
    assert session.committed == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_node_detail.py -q`
Expected: FAIL —— `AttributeError: ... has no attribute 'node_detail'`

- [ ] **Step 3: 实现 service**

在 `graph_service.py` 的 `snapshot` **之后**追加：

```python
PATH_GUARD = 10


def _ancestor_path(session: Session, node: KnowledgePoint) -> list[str]:
    """根 → 本节点的名称链（守卫 10 层，防脏数据成环）。"""
    names = [node.name]
    current = node
    guard = 0
    while current.parent_id is not None and guard < PATH_GUARD:
        parent = session.get(KnowledgePoint, current.parent_id)
        if parent is None:
            break
        names.append(parent.name)
        current = parent
        guard += 1
    names.reverse()
    return names


def _approved_neighbors(
    session: Session, kp_id: int
) -> dict[str, list[tuple[int, float | None]]]:
    """该节点参与的四类 approved 边，按 relation 分组返回 (对端 id, weight)。"""
    edges = list(
        session.scalars(
            select(KnowledgeEdge).where(
                KnowledgeEdge.review_status == EdgeReviewStatus.APPROVED,
                KnowledgeEdge.relation != EdgeRelation.CONTAINS.value,
                or_(
                    KnowledgeEdge.src_kp_id == kp_id,
                    KnowledgeEdge.dst_kp_id == kp_id,
                ),
            )
        )
    )
    grouped: dict[str, list[tuple[int, float | None]]] = {
        EdgeRelation.PREREQUISITE.value: [],
        EdgeRelation.RELATED.value: [],
        EdgeRelation.CONFUSABLE.value: [],
    }
    success: list[tuple[int, float | None]] = []
    for edge in edges:
        weight = float(edge.weight) if edge.weight is not None else None
        other = edge.dst_kp_id if edge.src_kp_id == kp_id else edge.src_kp_id
        if edge.relation == EdgeRelation.PREREQUISITE.value:
            if edge.dst_kp_id == kp_id:
                grouped[EdgeRelation.PREREQUISITE.value].append((other, weight))
            else:
                success.append((other, weight))
        else:
            grouped.setdefault(edge.relation, []).append((other, weight))
    grouped["successors"] = success
    return grouped


def node_detail(session: Session, *, kp_id: int, user_id: int) -> Any:
    """节点详情：面包屑 + 四类 approved 邻居 + 本人笔记与错题（S4-6，只读）。"""
    from app.models.mistake import Mistake
    from app.models.note import Note
    from app.models.note_kp import NoteKp
    from app.models.question import Question
    from app.models.question_kp import QuestionKp
    from app.schemas.kp import (
        GraphMistakeBrief,
        GraphNeighborOut,
        GraphNodeDetailOut,
        GraphNoteBrief,
    )

    node = session.get(KnowledgePoint, kp_id)
    if node is None:
        raise NotFoundError("知识点不存在")
    grouped = _approved_neighbors(session, kp_id)
    other_ids = {
        other_id for pairs in grouped.values() for other_id, _ in pairs
    }
    names = _names_by_id(session, other_ids)

    def neighbors(key: str) -> list[Any]:
        return [
            GraphNeighborOut(
                kp_id=other_id,
                name=names.get(other_id, f"#{other_id}"),
                weight=weight,
            )
            for other_id, weight in grouped.get(key, [])
        ]

    notes = session.execute(
        select(Note.id, Note.title, Note.updated_at)
        .join(NoteKp, NoteKp.note_id == Note.id)
        .where(NoteKp.kp_id == kp_id, NoteKp.confirmed.is_(True))
        .where(Note.user_id == user_id, Note.deleted_at.is_(None))
        .order_by(Note.updated_at.desc())
        .limit(20)
    ).all()
    mistakes = session.execute(
        select(
            Mistake.id,
            Mistake.question_id,
            Mistake.status,
            Mistake.created_at,
            Question.stem_md,
        )
        .join(Question, Question.id == Mistake.question_id)
        .join(QuestionKp, QuestionKp.question_id == Question.id)
        .where(QuestionKp.kp_id == kp_id, Mistake.user_id == user_id)
        .order_by(Mistake.created_at.desc())
        .limit(20)
    ).all()
    return GraphNodeDetailOut(
        id=node.id,
        name=node.name,
        level=node.level,
        parent_id=node.parent_id,
        subject_id=node.subject_id,
        path=_ancestor_path(session, node),
        description=node.description,
        exam_weight=(
            float(node.exam_weight) if node.exam_weight is not None else None
        ),
        mistake_count=len(mistakes),
        prerequisites=neighbors(EdgeRelation.PREREQUISITE.value),
        successors=neighbors("successors"),
        related=neighbors(EdgeRelation.RELATED.value),
        confusable=neighbors(EdgeRelation.CONFUSABLE.value),
        notes=[
            GraphNoteBrief(id=row[0], title=row[1], updated_at=row[2])
            for row in notes
        ],
        mistakes=[
            GraphMistakeBrief(
                id=row[0],
                question_id=row[1],
                status=row[2],
                created_at=row[3],
                stem=(row[4] or "")[:60],
            )
            for row in mistakes
        ],
    )
```

`_names_by_id` 写在 `_ancestor_path` 之前：

```python
def _names_by_id(session: Session, kp_ids: Any) -> dict[int, str]:
    """一次 IN 批查名称，避免逐个 get（禁止 N+1）。"""
    if not kp_ids:
        return {}
    rows = session.execute(
        select(KnowledgePoint.id, KnowledgePoint.name).where(
            KnowledgePoint.id.in_(list(kp_ids))
        )
    ).all()
    return {int(kp_id): name for kp_id, name in rows}
```

- [ ] **Step 4: 运行服务测试**

Run: `cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_graph_node_detail.py -q`
Expected: `7 passed`

- [ ] **Step 5: 追加路由**

`backend/app/api/v1/kp.py` 的 schema import 块补 `GraphNodeDetailOut`，在 `graph_snapshot` 之后插入：

```python
@router.get(
    "/graph/nodes/{kp_id}",
    response_model=Envelope[GraphNodeDetailOut],
    summary="知识点图谱详情",
)
def graph_node_detail(
    kp_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> Envelope[GraphNodeDetailOut]:
    return Envelope(
        trace_id=get_trace_id(),
        data=graph_service.node_detail(
            session, kp_id=kp_id, user_id=current_user.id
        ),
    )
```

- [ ] **Step 6: 接口层补 2 条用例**

在 `tests/test_graph_node_detail.py` 末尾追加：

```python
def test_node_detail_api_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/kp/graph/nodes/3").status_code == 401


def test_node_detail_api_forwards_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.models.user import User
    from app.schemas.kp import GraphNodeDetailOut

    user = User(
        username="student_s46", nickname="s", grade="高二", role="student", password_hash="x"
    )
    user.id = 50

    class _Session:
        def get(self, model, pk):  # noqa: ANN001, ANN201
            return user if model is User else None

        def scalar(self, statement):  # noqa: ANN001, ANN201
            return user if "users" in str(statement) else 0

        def flush(self) -> None:
            return None

    captured: dict[str, int] = {}

    def fake_detail(session, *, kp_id: int, user_id: int):  # noqa: ANN001, ANN202
        captured["kp_id"] = kp_id
        captured["user_id"] = user_id
        return GraphNodeDetailOut(
            id=kp_id, name="导数", level=3, parent_id=2, subject_id=7,
            path=["高中数学"], mistake_count=0,
        )

    monkeypatch.setattr(graph_service, "node_detail", fake_detail)
    app.dependency_overrides[get_db] = lambda: _Session()
    token = create_access_token(user_id=50, role="student").token
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/kp/graph/nodes/3", headers={"Authorization": f"Bearer {token}"}
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert captured == {"kp_id": 3, "user_id": 50}
    assert resp.json()["data"]["path"] == ["高中数学"]
```

- [ ] **Step 7: 全量回归 + 提交**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent && git add backend/app/services/graph_service.py backend/app/api/v1/kp.py backend/tests/test_graph_node_detail.py
git commit -m "feat(s4-6): 后端知识点图谱详情接口"
```

Expected: 后端全绿（1152 → 1161）。

---

### Task 3: 前端依赖、类型与 API 封装

**Files:**
- Modify: `web/package.json`（`npm install echarts@6.1.0` 自动写入）
- Create: `web/src/types/graph.ts`
- Create: `web/src/api/graph.ts`
- Create: `web/src/api/graph.spec.ts`

**Interfaces:**
- Produces:
  - `fetchGraphSnapshot(subjectId: number): Promise<GraphSnapshot>`
  - `fetchGraphNode(kpId: number): Promise<GraphNodeDetail>`
  - 类型：`GraphRelation`、`GraphSnapshot*`、`GraphNodeDetail`、`GraphNeighbor`、`GraphNoteBrief`、`GraphMistakeBrief`

- [ ] **Step 1: 安装依赖并确认版本**

Run: `cd study-agent/web && npm install echarts@6.1.0`
Expected: `package.json` 的 `dependencies` 出现 `"echarts": "^6.1.0"`；`npm ls echarts` 显示 6.1.0。

- [ ] **Step 2: 写失败的测试**

创建 `web/src/api/graph.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchGraphNode, fetchGraphSnapshot } from './graph'

const http = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/api/http', () => ({
  API_PREFIX: '/api/v1',
  default: http,
}))

function envelope<T>(data: T) {
  return { data: { code: 0, message: 'ok', trace_id: 'trace-1', data } }
}

const snapshot = {
  subject: { id: 7, name: '高中数学' },
  nodes: [{ id: 2, name: '导数', level: 3, parent_id: 1, exam_weight: 0.8, mistake_count: 1 }],
  edges: [{ src_kp_id: 1, dst_kp_id: 2, relation: 'prerequisite', weight: 0.9 }],
  stats: { nodes: 2, edges: 1, pending_edges: 50, by_relation: { prerequisite: 1 } },
}

const detail = {
  id: 3,
  name: '导数与函数的单调性',
  level: 3,
  parent_id: 2,
  subject_id: 7,
  path: ['高中数学', '导数及其应用'],
  description: null,
  exam_weight: 0.8,
  mistake_count: 0,
  prerequisites: [],
  successors: [],
  related: [],
  confusable: [],
  notes: [],
  mistakes: [],
}

beforeEach(() => {
  http.get.mockReset()
})

describe('graph api', () => {
  it('fetchGraphSnapshot 带 subject_id 查询参数并解包', async () => {
    http.get.mockResolvedValueOnce(envelope(snapshot))
    const result = await fetchGraphSnapshot(7)
    expect(http.get).toHaveBeenCalledWith('/api/v1/kp/graph/snapshot', {
      params: { subject_id: 7 },
    })
    expect(result.stats.pending_edges).toBe(50)
  })

  it('fetchGraphNode 按 kp_id 请求详情', async () => {
    http.get.mockResolvedValueOnce(envelope(detail))
    const result = await fetchGraphNode(3)
    expect(http.get).toHaveBeenCalledWith('/api/v1/kp/graph/nodes/3')
    expect(result.path).toEqual(['高中数学', '导数及其应用'])
    expect(result.description).toBeNull()
  })
})
```

- [ ] **Step 3: 运行确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/api/graph.spec.ts`
Expected: FAIL —— `Failed to resolve import "./graph"`

- [ ] **Step 4: 写类型**

创建 `web/src/types/graph.ts`：

```ts
export type GraphRelation = 'contains' | 'prerequisite' | 'related' | 'confusable'

export interface GraphSnapshotNode {
  id: number
  name: string
  level: number
  parent_id: number | null
  exam_weight: number | null
  mistake_count: number
}

export interface GraphSnapshotEdge {
  src_kp_id: number
  dst_kp_id: number
  relation: GraphRelation
  weight: number | null
}

export interface GraphSnapshotStats {
  nodes: number
  edges: number
  pending_edges: number
  by_relation: Record<string, number>
}

export interface GraphSnapshot {
  subject: { id: number; name: string }
  nodes: GraphSnapshotNode[]
  edges: GraphSnapshotEdge[]
  stats: GraphSnapshotStats
}

export interface GraphNeighbor {
  kp_id: number
  name: string
  weight: number | null
}

export interface GraphNoteBrief {
  id: number
  title: string
  updated_at: string
}

export interface GraphMistakeBrief {
  id: number
  question_id: number
  status: string
  created_at: string
  stem: string
}

export interface GraphNodeDetail {
  id: number
  name: string
  level: number
  parent_id: number | null
  subject_id: number
  path: string[]
  description: string | null
  exam_weight: number | null
  mistake_count: number
  prerequisites: GraphNeighbor[]
  successors: GraphNeighbor[]
  related: GraphNeighbor[]
  confusable: GraphNeighbor[]
  notes: GraphNoteBrief[]
  mistakes: GraphMistakeBrief[]
}
```

- [ ] **Step 5: 写 API 封装**

创建 `web/src/api/graph.ts`：

```ts
import http, { API_PREFIX, type ApiEnvelope } from '@/api/http'
import type { GraphNodeDetail, GraphSnapshot } from '@/types/graph'

export async function fetchGraphSnapshot(subjectId: number): Promise<GraphSnapshot> {
  const resp = await http.get<ApiEnvelope<GraphSnapshot>>(`${API_PREFIX}/kp/graph/snapshot`, {
    params: { subject_id: subjectId },
  })
  return resp.data.data
}

export async function fetchGraphNode(kpId: number): Promise<GraphNodeDetail> {
  const resp = await http.get<ApiEnvelope<GraphNodeDetail>>(
    `${API_PREFIX}/kp/graph/nodes/${kpId}`,
  )
  return resp.data.data
}
```

- [ ] **Step 6: 运行测试确认通过 + 提交**

```bash
cd study-agent/web && npm run test:run -- --pool=threads src/api/graph.spec.ts
cd study-agent && git add web/package.json web/package-lock.json web/src/types/graph.ts web/src/api/graph.ts web/src/api/graph.spec.ts
git commit -m "feat(s4-6): 引入 echarts 并封装图谱快照/详情 API"
```

Expected: `2 passed`；`npm ls echarts` 为 6.1.0（基线 204 → 206）。

---

### Task 4: `useGraphData` 纯函数（颜色/大小/边样式/过滤/降级/搜索/option）

**Files:**
- Create: `web/src/views/kp/useGraphData.ts`
- Create: `web/src/views/kp/useGraphData.spec.ts`

**Interfaces:**
- Produces（Task 5 直接调用）：
  - `DEGRADE_THRESHOLD = 300`
  - `nodeColor(mistakeCount: number): string`
  - `nodeSize(examWeight: number | null): number`
  - `EDGE_STYLES: Record<GraphRelation, EdgeStyle>`
  - `chapterOf(nodeId: number, nodes: Map<number, GraphSnapshotNode>): number`
  - `chapterOptions(nodes: GraphSnapshotNode[]): Array<{ id: number; name: string }>`
  - `selectVisible(snapshot: GraphSnapshot, options: SelectOptions): { nodes: GraphSnapshotNode[]; edges: GraphSnapshotEdge[]; degraded: boolean }`
  - `pickFocusNode(nodes: GraphSnapshotNode[]): number | null`
  - `matchNodes(nodes: GraphSnapshotNode[], keyword: string, limit?: number): GraphSnapshotNode[]`
  - `buildOption(nodes, edges, selectedId: number | null): Record<string, unknown>`
  - `SelectOptions = { relations: GraphRelation[]; activeChapters: Set<number> | null; focusId: number | null; threshold?: number }`

- [ ] **Step 1: 写失败的测试**

创建 `web/src/views/kp/useGraphData.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { GraphSnapshot, GraphSnapshotEdge, GraphSnapshotNode } from '@/types/graph'

import {
  DEGRADE_THRESHOLD,
  EDGE_STYLES,
  buildOption,
  chapterOf,
  chapterOptions,
  matchNodes,
  nodeColor,
  nodeSize,
  pickFocusNode,
  selectVisible,
} from './useGraphData'

function node(
  id: number,
  name: string,
  opts: Partial<GraphSnapshotNode> = {},
): GraphSnapshotNode {
  return {
    id,
    name,
    level: opts.level ?? 3,
    parent_id: opts.parent_id ?? 1,
    exam_weight: opts.exam_weight ?? 0.5,
    mistake_count: opts.mistake_count ?? 0,
  }
}

function edge(
  src: number,
  dst: number,
  relation: GraphSnapshotEdge['relation'] = 'prerequisite',
): GraphSnapshotEdge {
  return { src_kp_id: src, dst_kp_id: dst, relation, weight: 0.9 }
}

function snapshot(nodes: GraphSnapshotNode[], edges: GraphSnapshotEdge[]): GraphSnapshot {
  return {
    subject: { id: 7, name: '高中数学' },
    nodes,
    edges,
    stats: {
      nodes: nodes.length,
      edges: edges.length,
      pending_edges: 0,
      by_relation: {},
    },
  }
}

describe('nodeColor', () => {
  it('按错题数分三档', () => {
    expect(nodeColor(0)).toBe('#9aa4b2')
    expect(nodeColor(1)).toBe('#f0b429')
    expect(nodeColor(2)).toBe('#f0b429')
    expect(nodeColor(3)).toBe('#e5484d')
    expect(nodeColor(99)).toBe('#e5484d')
  })
})

describe('nodeSize', () => {
  it('考纲权重映射到 8–30，null 取下限', () => {
    expect(nodeSize(null)).toBe(8)
    expect(nodeSize(0)).toBe(8)
    expect(nodeSize(1)).toBe(30)
    expect(nodeSize(0.5)).toBe(19)
  })

  it('越界权重被 clamp', () => {
    expect(nodeSize(-1)).toBe(8)
    expect(nodeSize(2)).toBe(30)
  })
})

describe('EDGE_STYLES', () => {
  it('四类关系样式互不相同，前置带箭头', () => {
    expect(EDGE_STYLES.prerequisite.type).toBe('solid')
    expect(EDGE_STYLES.prerequisite.arrow).toBe(true)
    expect(EDGE_STYLES.related.type).toBe('dashed')
    expect(EDGE_STYLES.confusable.type).toBe('dotted')
    expect(EDGE_STYLES.contains.arrow).toBe(false)
  })
})

describe('chapterOf', () => {
  it('沿 parent 找到最近的 level=2 祖先，level 1 返回自身', () => {
    const nodes = new Map([
      [1, node(1, '高中数学', { level: 1, parent_id: null })],
      [2, node(2, '导数及其应用', { level: 2, parent_id: 1 })],
      [3, node(3, '导数的概念与运算', { level: 3, parent_id: 2 })],
      [4, node(4, '基本求导公式', { level: 4, parent_id: 3 })],
    ])
    expect(chapterOf(4, nodes)).toBe(2)
    expect(chapterOf(2, nodes)).toBe(2)
    expect(chapterOf(1, nodes)).toBe(1)
  })
})

describe('chapterOptions', () => {
  it('只列 level=2 的章，按 id 升序', () => {
    const options = chapterOptions([
      node(5, '三角函数', { level: 2 }),
      node(1, '高中数学', { level: 1, parent_id: null }),
      node(3, '函数', { level: 2 }),
    ])
    expect(options).toEqual([
      { id: 3, name: '函数' },
      { id: 5, name: '三角函数' },
    ])
  })
})

describe('selectVisible', () => {
  const nodes = [
    node(1, '高中数学', { level: 1, parent_id: null }),
    node(2, '函数', { level: 2, parent_id: 1 }),
    node(3, '导数及其应用', { level: 2, parent_id: 1 }),
    node(4, '单调性', { level: 3, parent_id: 2 }),
    node(5, '导数应用', { level: 3, parent_id: 3 }),
  ]
  const edges = [
    edge(2, 4, 'contains'),
    edge(3, 5, 'contains'),
    edge(4, 5, 'prerequisite'),
  ]

  it('contains 不在 relations 里时被过滤掉', () => {
    const visible = selectVisible(snapshot(nodes, edges), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: null,
    })
    expect(visible.edges).toHaveLength(1)
    expect(visible.degraded).toBe(false)
  })

  it('折叠章时该章节点与其边一并消失，level 1 恒在', () => {
    const visible = selectVisible(snapshot(nodes, edges), {
      relations: ['contains', 'prerequisite'],
      activeChapters: new Set([3]),
      focusId: null,
    })
    expect(visible.nodes.map((item) => item.id)).toEqual([1, 3, 5])
    expect(visible.edges.map((item) => [item.src_kp_id, item.dst_kp_id])).toEqual([
      [3, 5],
    ])
  })

  it('节点数超过阈值时只留焦点与一跳邻居', () => {
    const many = Array.from({ length: DEGRADE_THRESHOLD + 1 }, (_, index) =>
      node(100 + index, `节点${index}`, { level: 3, parent_id: 1 }),
    )
    const chain = [edge(100, 101), edge(101, 102), edge(103, 104)]
    const visible = selectVisible(snapshot(many, chain), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: 101,
    })
    expect(visible.degraded).toBe(true)
    expect(visible.nodes.map((item) => item.id).sort()).toEqual([100, 101, 102])
  })

  it('降级时没有焦点就用错题最多的节点', () => {
    const many = Array.from({ length: DEGRADE_THRESHOLD + 1 }, (_, index) =>
      node(100 + index, `节点${index}`, {
        level: 3,
        parent_id: 1,
        mistake_count: index === 7 ? 5 : 0,
      }),
    )
    const visible = selectVisible(snapshot(many, [edge(107, 108)]), {
      relations: ['prerequisite'],
      activeChapters: null,
      focusId: null,
    })
    expect(visible.degraded).toBe(true)
    expect(visible.nodes.map((item) => item.id).sort()).toEqual([107, 108])
  })
})

describe('pickFocusNode', () => {
  it('取错题最多者，同分取小 id，空数组返回 null', () => {
    expect(pickFocusNode([node(5, 'a', { mistake_count: 1 }), node(6, 'b', { mistake_count: 1 })])).toBe(5)
    expect(pickFocusNode([node(5, 'a', { mistake_count: 0 }), node(6, 'b', { mistake_count: 4 })])).toBe(6)
    expect(pickFocusNode([])).toBeNull()
  })
})

describe('matchNodes', () => {
  it('按名称中文子串匹配并限制条数', () => {
    const nodes = [node(1, '导数与函数的单调性'), node(2, '导数的实际应用'), node(3, '数列求和')]
    expect(matchNodes(nodes, '导数').map((item) => item.id)).toEqual([1, 2])
    expect(matchNodes(nodes, '  ')).toEqual([])
    expect(matchNodes(nodes, '导数', 1)).toHaveLength(1)
  })
})

describe('buildOption', () => {
  const nodes = [node(3, '单调性', { exam_weight: 1, mistake_count: 3 })]
  const edges = [edge(3, 5), edge(3, 5, 'confusable')]

  it('节点带 symbolSize/颜色，边带箭头与样式', () => {
    const option = buildOption(nodes, edges, null) as {
      series: Array<{ data: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }>
    }
    const series = option.series[0]
    expect(series.data[0]).toMatchObject({
      id: '3',
      name: '单调性',
      symbolSize: 30,
      itemStyle: { color: '#e5484d' },
    })
    const prerequisite = series.links[0] as { symbol: string[]; lineStyle: { color: string } }
    expect(prerequisite.symbol).toEqual(['none', 'arrow'])
    expect(prerequisite.lineStyle.color).toBe(EDGE_STYLES.prerequisite.color)
    const confusable = series.links[1] as { symbol?: string[]; lineStyle: { type: string } }
    expect(confusable.symbol).toBeUndefined()
    expect(confusable.lineStyle.type).toBe('dotted')
  })

  it('力导向参数固定，禁用于空集合也不报错', () => {
    const option = buildOption([], [], null) as {
      series: Array<{ layout: string; force: { repulsion: number }; data: unknown[] }>
    }
    expect(option.series[0].layout).toBe('force')
    expect(option.series[0].force.repulsion).toBe(220)
    expect(option.series[0].data).toEqual([])
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/useGraphData.spec.ts`
Expected: FAIL —— 无法解析 `./useGraphData`

- [ ] **Step 3: 实现**

创建 `web/src/views/kp/useGraphData.ts`：

```ts
/**
 * 图谱可视化的纯函数层（S4-6）。
 *
 * 拆出来的原因：ECharts 在 jsdom 里没有 canvas，页面级测试只能靠 mock；
 * 把「取数 → 可见集合 → option」全部做成纯函数，颜色/降级/过滤这些易错逻辑
 * 才能被直接断言。
 */
import type {
  GraphRelation,
  GraphSnapshot,
  GraphSnapshotEdge,
  GraphSnapshotNode,
} from '@/types/graph'

/** 节点数超过该值就只画焦点子图（卡片要求 >300 降级）。 */
export const DEGRADE_THRESHOLD = 300

export const COLOR_MISTAKE_NONE = '#9aa4b2'
export const COLOR_MISTAKE_FEW = '#f0b429'
export const COLOR_MISTAKE_MANY = '#e5484d'

export interface EdgeStyle {
  color: string
  type: 'solid' | 'dashed' | 'dotted'
  width: number
  arrow: boolean
}

export const EDGE_STYLES: Record<GraphRelation, EdgeStyle> = {
  contains: { color: '#cfd6e0', type: 'solid', width: 1, arrow: false },
  prerequisite: { color: '#3b82f6', type: 'solid', width: 1.4, arrow: true },
  related: { color: '#22c55e', type: 'dashed', width: 1.2, arrow: false },
  confusable: { color: '#f59e0b', type: 'dotted', width: 1.2, arrow: false },
}

export interface SelectOptions {
  relations: GraphRelation[]
  activeChapters: Set<number> | null
  focusId: number | null
  threshold?: number
}

/** 错题密度只作临时热力（真实掌握度是 S4-7）。 */
export function nodeColor(mistakeCount: number): string {
  if (mistakeCount <= 0) return COLOR_MISTAKE_NONE
  if (mistakeCount <= 2) return COLOR_MISTAKE_FEW
  return COLOR_MISTAKE_MANY
}

export function nodeSize(examWeight: number | null): number {
  const weight = Math.min(1, Math.max(0, examWeight ?? 0))
  return Math.round(8 + 22 * weight)
}

export function chapterOf(
  nodeId: number,
  nodes: Map<number, GraphSnapshotNode>,
): number {
  let current = nodes.get(nodeId)
  let guard = 0
  let lastId = nodeId
  while (current && guard < 10) {
    if (current.level <= 2) return current.id
    lastId = current.id
    current = current.parent_id === null ? undefined : nodes.get(current.parent_id)
    guard += 1
  }
  return lastId
}

export function chapterOptions(
  nodes: GraphSnapshotNode[],
): Array<{ id: number; name: string }> {
  return nodes
    .filter((node) => node.level === 2)
    .sort((left, right) => left.id - right.id)
    .map((node) => ({ id: node.id, name: node.name }))
}

export function pickFocusNode(nodes: GraphSnapshotNode[]): number | null {
  let best: GraphSnapshotNode | null = null
  for (const node of nodes) {
    if (
      best === null ||
      node.mistake_count > best.mistake_count ||
      (node.mistake_count === best.mistake_count && node.id < best.id)
    ) {
      best = node
    }
  }
  return best === null ? null : best.id
}

function subgraphAround(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
  focusId: number,
): { nodes: GraphSnapshotNode[]; edges: GraphSnapshotEdge[] } {
  const keep = new Set<number>([focusId])
  for (const edge of edges) {
    if (edge.src_kp_id === focusId) keep.add(edge.dst_kp_id)
    if (edge.dst_kp_id === focusId) keep.add(edge.src_kp_id)
  }
  return {
    nodes: nodes.filter((node) => keep.has(node.id)),
    edges: edges.filter(
      (edge) => keep.has(edge.src_kp_id) && keep.has(edge.dst_kp_id),
    ),
  }
}

export function selectVisible(
  snapshot: GraphSnapshot,
  options: SelectOptions,
): { nodes: GraphSnapshotNode[]; edges: GraphSnapshotEdge[]; degraded: boolean } {
  const threshold = options.threshold ?? DEGRADE_THRESHOLD
  const relationSet = new Set(options.relations)
  const nodesById = new Map(snapshot.nodes.map((node) => [node.id, node]))
  const edges = snapshot.edges.filter((edge) => relationSet.has(edge.relation))
  const chapterFilter = options.activeChapters
  const nodes =
    chapterFilter === null
      ? snapshot.nodes
      : snapshot.nodes.filter(
          (node) =>
            node.level <= 1 || chapterFilter.has(chapterOf(node.id, nodesById)),
        )
  const kept = new Set(nodes.map((node) => node.id))
  const keptEdges = edges.filter(
    (edge) => kept.has(edge.src_kp_id) && kept.has(edge.dst_kp_id),
  )
  if (nodes.length <= threshold) {
    return { nodes, edges: keptEdges, degraded: false }
  }
  const focusId = options.focusId ?? pickFocusNode(nodes)
  if (focusId === null) {
    return { nodes, edges: keptEdges, degraded: false }
  }
  return { ...subgraphAround(nodes, keptEdges, focusId), degraded: true }
}

export function matchNodes(
  nodes: GraphSnapshotNode[],
  keyword: string,
  limit = 20,
): GraphSnapshotNode[] {
  const needle = keyword.trim().toLowerCase()
  if (!needle) return []
  return nodes
    .filter((node) => node.name.toLowerCase().includes(needle))
    .slice(0, limit)
}

export function buildOption(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
  selectedId: number | null,
): Record<string, unknown> {
  return {
    animationDuration: 200,
    tooltip: {
      confine: true,
      formatter: (params: { dataType?: string; data?: { name?: string } }) =>
        params.dataType === 'node' ? (params.data?.name ?? '') : '',
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 220, gravity: 0.06, edgeLength: [40, 90] },
        label: { show: true, fontSize: 10, color: '#344054' },
        labelLayout: { hideOverlap: true },
        emphasis: { focus: 'adjacency', lineStyle: { width: 2 } },
        selectedMode: 'single',
        select: { itemStyle: { borderColor: '#111827', borderWidth: 2 } },
        data: nodes.map((node) => ({
          id: String(node.id),
          name: node.name,
          value: node.exam_weight ?? 0,
          symbolSize: nodeSize(node.exam_weight),
          itemStyle: { color: nodeColor(node.mistake_count) },
          selected: selectedId === node.id,
        })),
        links: edges.map((edge) => {
          const style = EDGE_STYLES[edge.relation] ?? EDGE_STYLES.related
          return {
            source: String(edge.src_kp_id),
            target: String(edge.dst_kp_id),
            lineStyle: {
              color: style.color,
              type: style.type,
              width: style.width,
              opacity: 0.7,
              curveness: 0.08,
            },
            ...(style.arrow ? { symbol: ['none', 'arrow'], symbolSize: [0, 6] } : {}),
          }
        }),
      },
    ],
  }
}
```

- [ ] **Step 4: 运行确认通过 + 提交**

```bash
cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/useGraphData.spec.ts
cd study-agent && git add web/src/views/kp/useGraphData.ts web/src/views/kp/useGraphData.spec.ts
git commit -m "feat(s4-6): 图谱纯函数层（颜色/大小/边样式/降级/搜索）"
```

Expected: `13 passed`（基线 206 → 219）。

---

### Task 5: `Graph.vue` 页面 + 路由 + 侧栏

**Files:**
- Create: `web/src/views/kp/Graph.vue`
- Create: `web/src/views/kp/Graph.spec.ts`
- Modify: `web/src/router/index.ts`（children 里 `knowledge` 之后加 `graph`）
- Modify: `web/src/layouts/nav.ts`（第 08 项）
- Modify: `web/src/layouts/MainLayout.spec.ts:61`（期望 7 → 8）

**Interfaces:**
- Consumes: `fetchGraphSnapshot`/`fetchGraphNode`（Task 3）、`selectVisible`/`buildOption`/`chapterOptions`/`matchNodes`/`DEGRADE_THRESHOLD`（Task 4）、`listSubjects`（既有）
- Produces: 路由 `/graph`（name `graph`）、导航项 `{ index: '08', label: '图谱', name: 'graph', path: '/graph' }`

- [ ] **Step 1: 写失败的测试**

创建 `web/src/views/kp/Graph.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphNodeDetail, GraphSnapshot } from '@/types/graph'

import Graph from './Graph.vue'

const charts = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
    dispatchAction: vi.fn(),
  }
  return { chart, init: vi.fn(() => chart), use: vi.fn() }
})

vi.mock('echarts/core', () => ({
  use: charts.use,
  init: charts.init,
}))
vi.mock('echarts/charts', () => ({ GraphChart: {} }))
vi.mock('echarts/components', () => ({ TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({
  fetchGraphSnapshot: vi.fn(),
  fetchGraphNode: vi.fn(),
  listSubjects: vi.fn(),
}))

vi.mock('@/api/graph', () => ({
  fetchGraphSnapshot: api.fetchGraphSnapshot,
  fetchGraphNode: api.fetchGraphNode,
}))
vi.mock('@/api/kp', () => ({ listSubjects: api.listSubjects }))

const store = vi.hoisted(() => ({ role: 'student' }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { role: store.role } }),
}))

function node(id: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    name,
    level: 3,
    parent_id: 2,
    exam_weight: 0.5,
    mistake_count: 0,
    ...extra,
  }
}

function snapshot(overrides: Partial<GraphSnapshot> = {}): GraphSnapshot {
  return {
    subject: { id: 7, name: '高中数学' },
    nodes: [
      { id: 1, name: '高中数学', level: 1, parent_id: null, exam_weight: 1, mistake_count: 0 },
      { id: 2, name: '函数', level: 2, parent_id: 1, exam_weight: 1, mistake_count: 0 },
      node(3, '单调性'),
      node(4, '导数与函数的单调性'),
    ],
    edges: [
      { src_kp_id: 3, dst_kp_id: 4, relation: 'prerequisite', weight: 0.9 },
    ],
    stats: {
      nodes: 4,
      edges: 1,
      pending_edges: 0,
      by_relation: { contains: 0, prerequisite: 1, related: 0, confusable: 0 },
    },
    ...overrides,
  }
}

const detail: GraphNodeDetail = {
  id: 4,
  name: '导数与函数的单调性',
  level: 3,
  parent_id: 2,
  subject_id: 7,
  path: ['高中数学', '导数及其应用', '导数与函数的单调性'],
  description: null,
  exam_weight: 0.8,
  mistake_count: 0,
  prerequisites: [{ kp_id: 3, name: '单调性', weight: 0.9 }],
  successors: [],
  related: [],
  confusable: [],
  notes: [],
  mistakes: [],
}

function mountPage() {
  return mount(Graph, {
    global: {
      stubs: {
        'el-drawer': {
          template: '<div data-testid="drawer"><slot /></div>',
          props: ['modelValue'],
        },
      },
    },
  })
}

beforeEach(() => {
  api.fetchGraphSnapshot.mockReset()
  api.fetchGraphNode.mockReset()
  api.listSubjects.mockReset()
  charts.init.mockClear()
  charts.chart.setOption.mockClear()
  charts.chart.on.mockClear()
  store.role = 'student'
  api.listSubjects.mockResolvedValue([
    { id: 7, name: '高中数学', code: 'math', stage: '高中' },
  ])
  api.fetchGraphSnapshot.mockResolvedValue(snapshot())
  api.fetchGraphNode.mockResolvedValue(detail)
})

describe('Graph 页面', () => {
  it('首屏拉快照并渲染画布', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.fetchGraphSnapshot).toHaveBeenCalledWith(7)
    expect(charts.init).toHaveBeenCalled()
    expect(charts.chart.setOption).toHaveBeenCalled()
    const first = charts.chart.setOption.mock.calls.at(-1)?.[0] as {
      series: Array<{ data: Array<{ id: string }> }>
    }
    // contains 默认关闭 → 只渲染前置链接线，节点仍是全部 4 个
    expect(first.series[0].data).toHaveLength(4)
    wrapper.unmount()
  })

  it('点节点打开抽屉并展示前置与空态', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const clickHandler = charts.chart.on.mock.calls.find(([name]) => name === 'click')?.[1] as (
      params: { dataType: string; data: { id: string } },
    ) => void
    clickHandler({ dataType: 'node', data: { id: '4' } })
    await flushPromises()
    expect(api.fetchGraphNode).toHaveBeenCalledWith(4)
    const text = wrapper.text()
    expect(text).toContain('导数与函数的单调性')
    expect(text).toContain('单调性')
    expect(text).toContain('暂无描述')
    expect(text).toContain('暂无关联笔记')
    wrapper.unmount()
  })

  it('节点超过阈值时显示降级横幅', async () => {
    const many = Array.from({ length: 301 }, (_, index) => node(100 + index, `节点${index}`))
    api.fetchGraphSnapshot.mockResolvedValue(snapshot({ nodes: many, edges: [] }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('降级为子图模式')
    wrapper.unmount()
  })

  it('老师看到待校验提示，学生看不到', async () => {
    api.fetchGraphSnapshot.mockResolvedValue(
      snapshot({
        stats: {
          nodes: 4,
          edges: 1,
          pending_edges: 50,
          by_relation: { contains: 0, prerequisite: 1, related: 0, confusable: 0 },
        },
      }),
    )
    const student = mountPage()
    await flushPromises()
    expect(student.text()).not.toContain('50 条待校验')
    student.unmount()

    store.role = 'teacher'
    const teacher = mountPage()
    await flushPromises()
    expect(teacher.text()).toContain('50 条待校验')
    teacher.unmount()
  })

  it('搜索选中节点后高亮并打开抽屉', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      keyword: string
      onPickSearch: (id: number) => void
    }
    vm.keyword = '导数'
    vm.onPickSearch(4)
    await flushPromises()
    expect(api.fetchGraphNode).toHaveBeenCalledWith(4)
    expect(charts.chart.dispatchAction).toHaveBeenCalled()
    wrapper.unmount()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/Graph.spec.ts`
Expected: FAIL —— 无法解析 `./Graph.vue`

- [ ] **Step 3: 实现页面**

创建 `web/src/views/kp/Graph.vue`（`<script setup lang="ts">` + 模板）：

```vue
<script setup lang="ts">
/**
 * 图谱可视化页（S4-6）。
 *
 * 画布只负责渲染：可见集合与 option 全在 useGraphData 的纯函数里，
 * 页面这一层只管请求、抽屉与工具栏状态。
 */
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchGraphNode, fetchGraphSnapshot } from '@/api/graph'
import { listSubjects } from '@/api/kp'
import PageHeader from '@/components/common/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'
import type { GraphNodeDetail, GraphRelation, GraphSnapshot } from '@/types/graph'

import {
  DEGRADE_THRESHOLD,
  buildOption,
  chapterOf,
  chapterOptions,
  matchNodes,
  selectVisible,
} from './useGraphData'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const RELATION_LABELS: Array<{ value: GraphRelation; label: string }> = [
  { value: 'contains', label: '结构（章→节）' },
  { value: 'prerequisite', label: '前置' },
  { value: 'related', label: '相关' },
  { value: 'confusable', label: '易混' },
]

const auth = useAuthStore()
const router = useRouter()
const canReview = computed(() => ['admin', 'teacher'].includes(auth.user?.role ?? ''))

const canvas = ref<HTMLDivElement | null>(null)
const snapshot = ref<GraphSnapshot | null>(null)
const subjects = ref<Array<{ id: number; name: string; code: string }>>([])
const subjectId = ref<number | null>(null)
const loading = ref(false)
const error = ref('')
const relations = ref<GraphRelation[]>(['prerequisite', 'related', 'confusable'])
const activeChapters = ref<number[] | null>(null)
const keyword = ref('')
const selectedId = ref<number | null>(null)
const showAllOverride = ref(false)
const drawerOpen = ref(false)
const detail = ref<GraphNodeDetail | null>(null)
const detailLoading = ref(false)

let chart: echarts.ECharts | null = null

const visible = computed(() => {
  if (snapshot.value === null) {
    return { nodes: [], edges: [], degraded: false }
  }
  return selectVisible(snapshot.value, {
    relations: relations.value,
    activeChapters: activeChapters.value === null ? null : new Set(activeChapters.value),
    focusId: selectedId.value,
    threshold: showAllOverride.value ? Number.MAX_SAFE_INTEGER : DEGRADE_THRESHOLD,
  })
})

const chapters = computed(() =>
  snapshot.value === null ? [] : chapterOptions(snapshot.value.nodes),
)
const searchResults = computed(() =>
  snapshot.value === null ? [] : matchNodes(snapshot.value.nodes, keyword.value),
)
const pendingEdges = computed(() => snapshot.value?.stats.pending_edges ?? 0)

function render(): void {
  if (chart === null) return
  chart.setOption(buildOption(visible.value.nodes, visible.value.edges, selectedId.value), {
    notMerge: true,
  })
}

async function loadSubjects(): Promise<void> {
  subjects.value = await listSubjects()
  if (subjectId.value === null) {
    subjectId.value = subjects.value[0]?.id ?? null
  }
}

async function loadSnapshot(): Promise<void> {
  if (subjectId.value === null) return
  loading.value = true
  error.value = ''
  try {
    snapshot.value = await fetchGraphSnapshot(subjectId.value)
    activeChapters.value = null
    showAllOverride.value = false
    render()
  } catch {
    error.value = '图谱加载失败，请重试'
  } finally {
    loading.value = false
  }
}

async function openDetail(kpId: number): Promise<void> {
  selectedId.value = kpId
  drawerOpen.value = true
  detailLoading.value = true
  detail.value = null
  // 等 visible 重算 + setOption 生效后再高亮，否则 dataIndex 是旧的
  await nextTick()
  highlightById(kpId)
  try {
    detail.value = await fetchGraphNode(kpId)
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function findIndex(kpId: number): number {
  return visible.value.nodes.findIndex((node) => node.id === kpId)
}

function highlightById(kpId: number): void {
  const index = findIndex(kpId)
  if (chart === null || index < 0) return
  chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: index })
  chart.dispatchAction({ type: 'select', seriesIndex: 0, dataIndex: index })
}

function onPickSearch(kpId: number): void {
  const target = snapshot.value?.nodes.find((node) => node.id === kpId)
  if (target !== undefined && activeChapters.value !== null && snapshot.value !== null) {
    const nodesById = new Map(snapshot.value.nodes.map((node) => [node.id, node]))
    const chapter = chapterOf(target.id, nodesById)
    if (!activeChapters.value.includes(chapter)) {
      activeChapters.value = [...activeChapters.value, chapter]
    }
  }
  void openDetail(kpId)
}

function onLegendChange(): void {
  render()
}

watch(visible, render)

onMounted(async () => {
  await loadSubjects()
  await loadSnapshot()
  if (canvas.value !== null) {
    chart = echarts.init(canvas.value)
    chart.on('click', (params: { dataType?: string; data?: { id?: string } }) => {
      if (params.dataType !== 'node' || params.data?.id === undefined) return
      void openDetail(Number(params.data.id))
    })
    render()
  }
})

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="graph-page">
    <PageHeader
      title="图谱"
      description="力导向知识图谱：节点大小=考纲权重，颜色=我的错题密度（临时指标，S4-7 换真实掌握度）。"
    />

    <div class="graph-toolbar">
      <el-select v-model="subjectId" placeholder="学科" style="width: 140px" @change="loadSnapshot">
        <el-option
          v-for="item in subjects"
          :key="item.id"
          :label="item.name"
          :value="item.id"
        />
      </el-select>
      <el-select
        v-model="activeChapters"
        multiple
        collapse-tags
        clearable
        placeholder="全部模块"
        style="min-width: 220px"
        @change="onLegendChange"
      >
        <el-option v-for="item in chapters" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-checkbox-group v-model="relations" @change="onLegendChange">
        <el-checkbox v-for="item in RELATION_LABELS" :key="item.value" :value="item.value">
          {{ item.label }}
        </el-checkbox>
      </el-checkbox-group>
      <el-select
        v-model="keyword"
        filterable
        remote
        clearable
        :remote-method="() => undefined"
        placeholder="搜索知识点"
        style="width: 200px"
      >
        <el-option
          v-for="item in searchResults"
          :key="item.id"
          :label="item.name"
          :value="item.name"
          @click="onPickSearch(item.id)"
        />
      </el-select>
      <el-button :loading="loading" @click="loadSnapshot">刷新</el-button>
      <el-link
        v-if="canReview && pendingEdges > 0"
        type="warning"
        data-testid="pending-hint"
        @click="router.push('/knowledge')"
      >
        还有 {{ pendingEdges }} 条待校验
      </el-link>
    </div>

    <el-alert
      v-if="visible.degraded"
      type="warning"
      :closable="false"
      show-icon
      title="节点过多，已降级为子图模式（只显示焦点与一跳邻居）"
    >
      <el-button size="small" @click="showAllOverride = true">显示全部（可能卡顿）</el-button>
    </el-alert>

    <el-alert v-if="error" type="error" :closable="false" :title="error" />

    <div ref="canvas" class="graph-canvas" data-testid="graph-canvas" />

    <el-drawer v-model="drawerOpen" size="420px" :title="detail?.name ?? '知识点详情'">
      <div v-loading="detailLoading" class="graph-detail">
        <template v-if="detail !== null">
          <p class="graph-detail__path">{{ detail.path.join(' / ') }}</p>
          <p>
            考纲权重：{{ detail.exam_weight ?? '—' }} ·
            层级 L{{ detail.level }} ·
            我的错题：{{ detail.mistake_count }} 条
          </p>
          <h4>描述</h4>
          <p v-if="detail.description">{{ detail.description }}</p>
          <p v-else class="graph-detail__empty">暂无描述</p>

          <template v-for="group in [
            { title: '前置', items: detail.prerequisites },
            { title: '后继', items: detail.successors },
            { title: '相关', items: detail.related },
            { title: '易混', items: detail.confusable },
          ]" :key="group.title">
            <h4>{{ group.title }}</h4>
            <p v-if="group.items.length === 0" class="graph-detail__empty">暂无</p>
            <ul v-else class="graph-detail__list">
              <li v-for="item in group.items" :key="item.kp_id">
                <el-link type="primary" @click="openDetail(item.kp_id)">{{ item.name }}</el-link>
              </li>
            </ul>
          </template>

          <h4>关联笔记</h4>
          <p v-if="detail.notes.length === 0" class="graph-detail__empty">暂无关联笔记</p>
          <ul v-else class="graph-detail__list">
            <li v-for="note in detail.notes" :key="note.id">
              <el-link type="primary" @click="router.push(`/notes/${note.id}`)">{{ note.title }}</el-link>
            </li>
          </ul>

          <h4>我的错题</h4>
          <p v-if="detail.mistakes.length === 0" class="graph-detail__empty">暂无错题</p>
          <ul v-else class="graph-detail__list">
            <li v-for="mistake in detail.mistakes" :key="mistake.id">
              <el-link type="primary" @click="router.push(`/mistakes/${mistake.id}`)">
                #{{ mistake.id }} · {{ mistake.status }}
              </el-link>
              <span class="graph-detail__stem">{{ mistake.stem }}</span>
            </li>
          </ul>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.graph-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.graph-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.graph-canvas {
  height: calc(100vh - 260px);
  min-height: 480px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fbfcfe;
}
.graph-detail__path {
  color: #6b7280;
  font-size: 12px;
}
.graph-detail__empty {
  color: #9ca3af;
}
.graph-detail__list {
  padding-left: 18px;
}
.graph-detail__stem {
  margin-left: 8px;
  color: #6b7280;
  font-size: 12px;
}
</style>
```

- [ ] **Step 4: 注册路由与导航**

`web/src/router/index.ts` 在 `knowledge` 路由之后插入：

```ts
        {
          path: 'graph',
          name: 'graph',
          component: () => import('@/views/kp/Graph.vue'),
          meta: { title: '图谱', nav: 'graph' },
        },
```

`web/src/layouts/nav.ts` 末尾追加：

```ts
  { index: '08', label: '图谱', name: 'graph', path: '/graph' },
```

`web/src/layouts/MainLayout.spec.ts:61` 改成：

```ts
    expect(wrapper.findAll('[data-testid="nav-link"]')).toHaveLength(8)
```

- [ ] **Step 5: 运行前端测试**

Run: `cd study-agent/web && npm run test:run -- --pool=threads src/views/kp/Graph.spec.ts src/layouts/MainLayout.spec.ts`
Expected: `Graph.spec.ts` 5 passed；MainLayout 全绿

- [ ] **Step 6: 全量测试 + 构建**

```bash
cd study-agent/web && npm run test:run -- --pool=threads
cd study-agent/web && npm run build
```

Expected: 前端全绿（219 → 224 左右）；`npm run build` 退出 0。

- [ ] **Step 7: 提交**

```bash
cd study-agent && git add web/src/views/kp/Graph.vue web/src/views/kp/Graph.spec.ts web/src/router/index.ts web/src/layouts/nav.ts web/src/layouts/MainLayout.spec.ts
git commit -m "feat(s4-6): 图谱可视化页面（力导向、模块折叠、搜索、降级）"
```

---

### Task 6: 文档同步 + 真机验收 + 合并

**Files:**
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-049）、`docs/SCHEMA.md`（§3.2 旁注）、`README.md`
- Create: `.sdd/s4-6/acceptance-evidence.md`、`.sdd/s4-6/progress.md`

- [ ] **Step 1: 启动服务并做真机验收**

```bash
# 终端 A（后台）
cd study-agent/backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8032
# 终端 B
cd study-agent/web && npm run dev
```

验收清单（逐条记录实测值）：
1. `/graph` 首屏耗时（DevTools Network + Performance，navigation → 画布出现节点）**<3s**。
2. 点「导数与函数的单调性」→ 抽屉显示前置「函数的单调性」可点击、笔记区空态文案。
3. `contains` 开关打开后出现灰细线；前置有箭头；相关虚线；易混点线。
4. 折叠「解析几何」→ 该章节点与边消失。
5. 搜索「导数」→ 命中并高亮，抽屉打开。
6. 降级：临时把 `DEGRADE_THRESHOLD` 改 20 → 刷新确认横幅与子图；**改回 300 并重新构建**。
7. 学生账号打开无「待校验」提示；老师账号有。

- [ ] **Step 2: 写证据与进度文档**

`.sdd/s4-6/acceptance-evidence.md` 必须包含：环境、账号、每个验收项的实测数字/截图路径、降级临时改动记录、未验证项（浏览器 E2E 不存在、真实掌握度未接）。

`.sdd/s4-6/progress.md` 必须包含：与 plan 的偏离（如 `contains` 默认关闭、力导向不固定布局）、临时数据改动、遗留项。

- [ ] **Step 3: 更新文档四件套**

- `docs/PROGRESS.md`：S4-6 状态打勾、最近完成改成 S4-6、关键口径段、验收段（实测数字）、下一步改 S4-7。
- `docs/DECISIONS.md`：新增 `## D-049 图谱可视化前端（S4-6）`，覆盖：临时热力指标（S4-7 替换）、`contains` 默认关闭、降级阈值 300、echarts 按需引入、力导向布局不固定、只显示 approved 边、笔记/错题本人口径。
- `docs/SCHEMA.md`：§3.2 旁注「图谱读取为只读接口，掌握度配色待 S4-7 接入」。
- `README.md`：启动段补「图谱页 `/graph`（力导向，老师账号能看到待校验提示）」。

- [ ] **Step 4: 全量回归**

```bash
cd study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q
cd study-agent/web && npm run test:run -- --pool=threads
cd study-agent/web && npm run build
```

Expected: 后端 1161 passed；前端全绿；build 退出 0。

- [ ] **Step 5: 提交并 ff-merge**

```bash
cd study-agent && git add docs README.md .sdd/s4-6 2>/dev/null || git add docs README.md
git commit -m "docs(s4-6): 同步 PROGRESS/DECISIONS/SCHEMA/README 与验收证据"
git checkout main && git merge --ff-only feature/s4-6-graph-view && git branch -d feature/s4-6-graph-view
# 不 push（用户自己推）
```

---

## 风险与回退

- ECharts 在 jsdom 下不可用 → 页面测试一律 mock `echarts/core`（Task 5 已给 mock）。
- 力导向布局每次不同 → 测试只断言 option 结构，不断言坐标。
- 若 `npm install echarts@6.1.0` 因网络失败 → 先 `npm view echarts version` 确认可达；仍失败则停下来报告，**不要**换成本地图纸方案（依赖已确认，不擅自改选型）。
- 若真机 <3s 不达标 → 先看是不是首屏同时拉了 `/kp/subjects` + 快照（可合并），再考虑边数降到只画前置；**不许**为了让数字好看而隐藏节点。