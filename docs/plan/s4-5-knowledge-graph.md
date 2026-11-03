# S4-5 知识图谱关系构建 + 人工校验 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 subject 7 的 108 个知识点上建成四类关系边（contains 派生、prerequisite LLM 推断、related/confusable 向量候选+LLM 复核），AI 边默认待校验，admin/teacher 在界面逐条通过/驳回。

**Architecture:** 纯函数层（候选构造/阈值分档/方向守卫）与 LLM 适配层分离，`services/graph_service.py` 负责编排、幂等与墓碑语义；写库走 ORM 载入比对（先查现有边再决定 add/update/skip），异常与重试在适配层。审核三列落在 `knowledge_edges`，`llm_call_logs.scene` 加 `graph`。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / pgvector / ARQ / Vue 3 + TS + Element Plus + Vitest

**Spec:** `docs/spec/s4-5-knowledge-graph.md`

## Global Constraints

- 分层：路由只做参数校验 + `Envelope`，业务逻辑在 `services/`，LLM 调用只在 `ai/` 层（`AGENTS.md §4`）
- LLM 一律走 `app/ai/llm` 的 `get_llm_client()`，`scene="graph"`，`client.chat(messages, *, temperature=None, max_tokens=None, scene="qa")`，消息用 `LLMMessage(role=..., content=...)`
- Bundle 输出解析统一 `from app.ai.gen.json_repair import loads_lenient_json`（模型输出公式时常漏转义反斜杠）
- 结构化输出必须 Pydantic 校验 + 最多 2 次逻辑重试；失败抛 `GraphBuildError`（`AppError` 子类，`500/50000`）
- 枚举一律 TEXT + CHECK：值集常量进 `app/models/enums.py`，CHECK 文本由 `in_check()` 生成
- 路由函数 ≤30 行；service 一个用例一个事务；任务 handler `(Session, payload)` **不得自行 commit**
- 列表接口统一 `page_params` / `sort_params` / `paginate_query` / `apply_sort`（`app/utils/pagination.py`），排序字段走白名单
- 所有学生数据查询显式带 `user_id`；本卡接口只对 `admin`/`teacher` 开放（`require_role`）
- 禁止新增依赖；不修改已提交的迁移文件（新增 `0012_s4_5`）
- 后端测试命令（在 `backend/` 下）：`..\.venv\Scripts\python.exe -m pytest -q`
- 前端测试命令（在 `web/` 下）：`npm run test:run -- --pool=threads`，构建 `npm run build`
- 提交信息带任务号：`feat(s4-5):` / `test(s4-5):` / `docs(s4-5):` / `fix(s4-5):`
- 基线：后端 **1082 passed, 1 warning**；前端 **194 passed / 35 files**；`alembic heads` = `0011_s4_3`

---

### Task 1: 契约先行——SCHEMA/API 文档 + 迁移 `0012_s4_5` + 枚举 + 模型

**Files:**
- Modify: `docs/SCHEMA.md`（§3.2 三列 + §10.17 值集）
- Modify: `docs/API.md`（新增 §4.5 五条接口）
- Create: `backend/alembic/versions/0012_s4_5.py`
- Modify: `backend/app/models/enums.py`（`EdgeReviewStatus`、`LLMCallScene.GRAPH`）
- Modify: `backend/app/models/knowledge_edge.py`（三列 + 两条 CHECK + 索引）
- Test: `backend/tests/test_graph_migration.py`

**Interfaces:**
- Produces:
  - `app.models.enums.EdgeReviewStatus`：`PENDING = "pending"` / `APPROVED = "approved"` / `REJECTED = "rejected"`
  - `app.models.enums.LLMCallScene.GRAPH = "graph"`
  - `KnowledgeEdge.review_status: str`（非空，默认 `"pending"`）、`KnowledgeEdge.reviewed_by: int | None`、`KnowledgeEdge.reviewed_at: datetime | None`

- [ ] **Step 1: 改 `docs/SCHEMA.md` §3.2**

在 `knowledge_edges` 表格末尾追加三行（紧跟 `updated_at` 之后）：

```markdown
| review_status | TEXT | 否 | 'pending' | 审核状态，§10.17（S4-5） | idx |
| reviewed_by | BIGINT | 是 | — | 审核人 users.id，FK ON DELETE SET NULL（S4-5） | — |
| reviewed_at | TIMESTAMPTZ | 是 | — | 最近一次审核时间（S4-5） | — |
```

在该表下方的说明段落追加：

```markdown
> S4-5 新增 `ck_knowledge_edges_review_status`（待校验/通过/驳回）与 `ck_knowledge_edges_reviewed`（`pending` 时 `reviewed_at` 必须为空，非 `pending` 时非空；`reviewed_by` 允许空以支持脚本批量通过）。迁移 `0012_s4_5` 把历史行回填为 `approved`；`contains` 派生边一律直接 `approved`。
```

§10 值集表追加一行（在 10.16 之后）：

```markdown
| 10.17 | knowledge_edges.review_status（`EdgeReviewStatus`） | pending / approved / rejected ✅（S4-5） | 本卡 S4-5 |
```

同时把 §10.14 的 `llm_call_logs.scene` 说明改为：

```markdown
| 10.14 | llm_call_logs.scene | qa / query_rewrite / kp_align / embed / mistake / gen / graph / agent（S4-5 加 graph） | 本卡 S3-7 + S4-5 |
```

- [ ] **Step 2: 改 `docs/API.md`，在 §4（知识点）之后新增 §4.5**

```markdown
### 4.5 知识图谱关系（S4-5）

> 四类关系：`contains`（树派生）/ `prerequisite`（LLM 推断）/ `related` / `confusable`（向量候选 + LLM 复核）。AI 推断的边默认 `review_status='pending'`，只有人工通过才是 `approved`。全部接口仅 `admin` / `teacher`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/kp/graph/build` | 202 + `TaskOut`，异步构建；body 可选 `{"relations": ["contains","prerequisite","related","confusable"], "limit": 50}` |
| GET | `/api/v1/kp/graph/edges` | 边列表，分页排序；参数 `status`（默认 `pending`，可选 `approved`/`rejected`/`all`）、`relation`、`subject_id`、`q`（任一端名称包含） |
| POST | `/api/v1/kp/graph/edges/{edge_id}/review` | `{"approve": true}` → 200 单条边；幂等 |
| POST | `/api/v1/kp/graph/edges/review` | `{"edge_ids": [1,2], "approve": false}` → `{"updated": 2, "skipped": 0}` |
| GET | `/api/v1/kp/graph/stats` | 节点数、按 relation/status 的计数、最近构建时间 |

`GraphEdgeOut`：

```json
{"id": 12, "src_kp_id": 3, "src_name": "函数单调性", "dst_kp_id": 8, "dst_name": "导数应用",
 "relation": "prerequisite", "weight": 0.82, "source": "ai", "review_status": "pending",
 "reviewed_at": null, "created_at": "2026-11-04T01:00:00Z"}
```

错误：`403/40300`（学生调用）、`404/40400`（边不存在）、`422/42200`（参数非法）、`500/50000`（队列不可用）。
```

- [ ] **Step 3: 写迁移 `backend/alembic/versions/0012_s4_5.py`**

```python
"""S4-5 知识图谱：knowledge_edges 审核三列 + llm_call_logs.scene 加 graph。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_s4_5"
down_revision = "0011_s4_3"
branch_labels = None
depends_on = None

RELATION_CHECK = "review_status IN ('pending', 'approved', 'rejected')"
REVIEWED_CHECK = (
    "(review_status = 'pending' AND reviewed_at IS NULL) "
    "OR (review_status <> 'pending' AND reviewed_at IS NOT NULL)"
)
SCENE_CHECK = (
    "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', "
    "'graph', 'agent')"
)


def upgrade() -> None:
    op.add_column(
        "knowledge_edges",
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
    )
    op.add_column(
        "knowledge_edges", sa.Column("reviewed_by", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "knowledge_edges",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_edges_reviewed_by",
        "knowledge_edges",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_knowledge_edges_review_status", "knowledge_edges", RELATION_CHECK
    )
    op.create_check_constraint(
        "ck_knowledge_edges_reviewed", "knowledge_edges", REVIEWED_CHECK
    )
    op.create_index(
        "ix_knowledge_edges_review_status", "knowledge_edges", ["review_status"]
    )
    # 历史边一律视为人工已通过，避免上线瞬间整图变成"待校验"
    op.execute(
        "UPDATE knowledge_edges SET review_status = 'approved', reviewed_at = now() "
        "WHERE review_status = 'pending'"
    )
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint("ck_llm_call_logs_scene", "llm_call_logs", SCENE_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_llm_call_logs_scene", "llm_call_logs", type_="check")
    op.create_check_constraint(
        "ck_llm_call_logs_scene",
        "llm_call_logs",
        "scene IN ('qa', 'query_rewrite', 'kp_align', 'embed', 'mistake', 'gen', 'agent')",
    )
    op.drop_index("ix_knowledge_edges_review_status", table_name="knowledge_edges")
    op.drop_constraint("ck_knowledge_edges_reviewed", "knowledge_edges", type_="check")
    op.drop_constraint(
        "ck_knowledge_edges_review_status", "knowledge_edges", type_="check"
    )
    op.drop_constraint(
        "fk_knowledge_edges_reviewed_by", "knowledge_edges", type_="foreignkey"
    )
    op.drop_column("knowledge_edges", "reviewed_at")
    op.drop_column("knowledge_edges", "reviewed_by")
    op.drop_column("knowledge_edges", "review_status")
```

- [ ] **Step 4: 改 `backend/app/models/enums.py`**

在 `EdgeSource` 之后插入：

```python
class EdgeReviewStatus(StrEnum):
    """knowledge_edges.review_status：AI 边的审核状态（SCHEMA §10.17，S4-5）。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
```

在 `LLMCallScene` 里 `GEN = "gen"` 之后插入 `GRAPH = "graph"`。

- [ ] **Step 5: 改 `backend/app/models/knowledge_edge.py`**

`__table_args__` 追加：

```python
        CheckConstraint(
            in_check("review_status", EdgeReviewStatus),
            name="ck_knowledge_edges_review_status",
        ),
        CheckConstraint(
            "(review_status = 'pending' AND reviewed_at IS NULL) "
            "OR (review_status <> 'pending' AND reviewed_at IS NOT NULL)",
            name="ck_knowledge_edges_reviewed",
        ),
        Index("ix_knowledge_edges_review_status", "review_status"),
```

列定义（放在 `source` 之后）：

```python
    review_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=EdgeReviewStatus.PENDING.value,
        default=EdgeReviewStatus.PENDING.value,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", name="fk_knowledge_edges_reviewed_by", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

import 行补 `EdgeReviewStatus`。

- [ ] **Step 6: 写迁移回归测试 `backend/tests/test_graph_migration.py`**

```python
"""S4-5 迁移与模型契约：三列、两条 CHECK、scene 白名单。"""
from __future__ import annotations

from app.models.enums import EdgeReviewStatus, LLMCallScene, in_check
from app.models.knowledge_edge import KnowledgeEdge


def test_edge_has_review_columns():
    columns = set(KnowledgeEdge.__table__.columns.keys())
    assert {"review_status", "reviewed_by", "reviewed_at"} <= columns


def test_review_status_check_renders_all_three_values():
    assert in_check("review_status", EdgeReviewStatus) == (
        "review_status IN ('pending', 'approved', 'rejected')"
    )


def test_scene_whitelist_contains_graph():
    assert "graph" in [scene.value for scene in LLMCallScene]


def test_review_status_default_is_pending():
    column = KnowledgeEdge.__table__.columns["review_status"]
    assert column.server_default.arg == "pending"
```

- [ ] **Step 7: 跑测试确认失败（模型还没列）**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_migration.py -q`
Expected: FAIL（`{"review_status", ...} <= columns` 断言失败）

- [ ] **Step 8: 上库并验证迁移**

```bash
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head      # 输出 Running upgrade 0011_s4_3 -> 0012_s4_5
..\.venv\Scripts\python.exe -m alembic heads             # 期望 0012_s4_5 (head)
..\.venv\Scripts\python.exe -m alembic check             # 期望 No new upgrade operations detected.
..\.venv\Scripts\python.exe -m pytest tests/test_graph_migration.py -q   # 期望 4 passed
```

实测列：

```bash
..\.venv\Scripts\python.exe -c "
from sqlalchemy import text
from app.core.db import new_session
s = new_session()
print(s.execute(text('''select column_name, is_nullable, column_default from information_schema.columns
 where table_name='knowledge_edges' and column_name in ('review_status','reviewed_by','reviewed_at')''')).all())
print(s.execute(text('''select conname from pg_constraint where conrelid='knowledge_edges'::regclass and conname like 'ck_knowledge_edges_review%' ''')).all())
s.close()"
```

- [ ] **Step 9: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add docs/SCHEMA.md docs/API.md backend/alembic/versions/0012_s4_5.py \
  backend/app/models/enums.py backend/app/models/knowledge_edge.py \
  backend/tests/test_graph_migration.py
git commit -m "feat(s4-5): 迁移 0012 给 knowledge_edges 加审核三列，scene 白名单加 graph"
```

---

### Task 2: 纯函数层 `ai/graph/candidates.py`

**Files:**
- Create: `backend/app/ai/graph/__init__.py`（空文件 + 模块 docstring）
- Create: `backend/app/ai/graph/candidates.py`
- Test: `backend/tests/test_graph_candidates.py`

**Interfaces:**
- Consumes: `from app.ai.align.scoring import cosine`
- Produces:
  - `@dataclass(frozen=True) KpBrief(kp_id: int, name: str, level: int, parent_id: int | None, embedding: list[float] | None, path: str)`
  - `build_paths(nodes: Sequence[KpBrief]) -> dict[int, str]`：`id → "父 / 子"` 路径字符串
  - `prereq_candidates(target: KpBrief, nodes: Sequence[KpBrief], paths: Mapping[int, str], *, top_k: int = 8, exclude_ids: AbstractSet[int] = frozenset()) -> list[KpCandidate]`，返回按 `cos` 降序的候选（`KpCandidate(kp_id, name, path, cos)`）
  - `pair_candidates(nodes, *, related_lo=0.75, related_hi=0.90, confusable_lo=0.90, same_parent_lo=0.75, top_k=8) -> tuple[list[Pair], list[Pair]]`：返回 `(related_pairs, confusable_pairs)`，`Pair(src_kp_id:int, dst_kp_id:int, cos:float)`，保证 `src_kp_id < dst_kp_id`
  - `direction_conflicts(existing: Sequence[tuple[int, int, str]]) -> set[tuple[int, int]]`：给出现存 `prerequisite` 边，返回需要跳过的 `(src, dst)` 集合（即与待插入边反向冲突的对）

- [ ] **Step 1: 写失败测试 `backend/tests/test_graph_candidates.py`**

```python
"""S4-5 候选构造纯函数：路径、前置候选、相似度分档、方向守卫。"""
from __future__ import annotations

from app.ai.graph.candidates import (
    KpBrief,
    Pair,
    build_paths,
    direction_conflicts,
    pair_candidates,
    prereq_candidates,
)


def _kp(kp_id: int, name: str, level: int, parent_id: int | None, vec: list[float] | None = None) -> KpBrief:
    return KpBrief(kp_id=kp_id, name=name, level=level, parent_id=parent_id, embedding=vec, path="")


def test_build_paths_joins_ancestors():
    nodes = [_kp(1, "函数", 1, None), _kp(2, "单调性", 2, 1), _kp(3, "比较大小", 3, 2)]
    assert build_paths(nodes) == {1: "函数", 2: "函数 / 单调性", 3: "函数 / 单调性 / 比较大小"}


def test_prereq_candidates_sorted_by_cosine_and_excludes_parent():
    target = _kp(10, "导数应用", 3, 2, [1.0, 0.0])
    nodes = [
        target,
        _kp(2, "单调性", 2, 1, [0.9, 0.1]),
        _kp(11, "极值", 3, 2, [0.1, 1.0]),
        _kp(12, "向量", 3, 5, [0.0, 1.0]),
        _kp(13, "无关", 3, 6, [-1.0, 0.0]),
    ]
    picked = prereq_candidates(target, nodes, build_paths(nodes), top_k=2, exclude_ids={2})
    assert [item.kp_id for item in picked] == [11, 12]
    assert picked[0].cos > picked[1].cos


def test_prereq_candidates_skip_nodes_without_embedding():
    target = _kp(10, "导数应用", 3, 2, [1.0, 0.0])
    nodes = [target, _kp(11, "极值", 3, 2, None)]
    assert prereq_candidates(target, nodes, build_paths(nodes)) == []


def test_pair_candidates_buckets_by_threshold():
    # 余弦 0.96 → confusable；0.80 → related；0.50 → 丢弃
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 200, [0.96, 0.28])
    c = _kp(3, "C", 3, 300, [0.80, 0.60])
    d = _kp(4, "D", 3, 400, [0.50, 0.866])
    related, confusable = pair_candidates([a, b, c, d])
    assert Pair(1, 3, related[0].cos) in related
    assert all(pair.src_kp_id < pair.dst_kp_id for pair in [*related, *confusable])
    assert (1, 2) not in {(p.src_kp_id, p.dst_kp_id) for p in related}
    assert (1, 2) in {(p.src_kp_id, p.dst_kp_id) for p in confusable}


def test_pair_candidates_same_parent_uses_lower_threshold():
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 100, [0.80, 0.60])
    _, confusable = pair_candidates([a, b])
    assert (1, 2) in {(p.src_kp_id, p.dst_kp_id) for p in confusable}


def test_pair_candidates_skip_same_parent_for_related():
    a = _kp(1, "A", 3, 100, [1.0, 0.0])
    b = _kp(2, "B", 3, 100, [0.80, 0.60])
    related, _ = pair_candidates([a, b])
    assert related == []


def test_direction_conflicts_flags_reverse_edge():
    existing = [(5, 6, "prerequisite"), (9, 8, "related")]
    assert direction_conflicts(existing) == {(5, 6)}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_candidates.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph'`

- [ ] **Step 3: 实现 `backend/app/ai/graph/candidates.py`**

```python
"""S4-5 图谱候选构造：全部纯函数，便于穷举边界。

设计取舍：
- 候选只看 top_k 近邻而非全量两两比较（O(n²) 在 108 节点尚可，但真到千级会拖死）；
- related 与 confusable 必须靠阈值区分，否则同一对会被两个 Prompt 各判一次、语义重叠；
- 无向关系统一按 (小 id, 大 id) 存一次，避免正反两条重复边。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import AbstractSet

from app.ai.align.scoring import cosine

RELATED_LO = 0.75
RELATED_HI = 0.90
CONFUSABLE_LO = 0.90
SAME_PARENT_LO = 0.75
TOPK = 8
PATH_GUARD = 10


@dataclass(frozen=True, slots=True)
class KpBrief:
    kp_id: int
    name: str
    level: int
    parent_id: int | None
    embedding: list[float] | None = None
    path: str = ""


@dataclass(frozen=True, slots=True)
class KpCandidate:
    kp_id: int
    name: str
    path: str
    cos: float


@dataclass(frozen=True, slots=True)
class Pair:
    src_kp_id: int
    dst_kp_id: int
    cos: float


def build_paths(nodes: Sequence[KpBrief]) -> dict[int, str]:
    by_id = {node.kp_id: node for node in nodes}
    paths: dict[int, str] = {}
    for node in nodes:
        names: list[str] = []
        cursor: KpBrief | None = node
        guard = 0
        while cursor is not None and guard < PATH_GUARD:
            names.append(cursor.name)
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id is not None else None
            guard += 1
        paths[node.kp_id] = " / ".join(reversed(names))
    return paths


def prereq_candidates(
    target: KpBrief,
    nodes: Sequence[KpBrief],
    paths: Mapping[int, str],
    *,
    top_k: int = TOPK,
    exclude_ids: AbstractSet[int] = frozenset(),
) -> list[KpCandidate]:
    if not target.embedding:
        return []
    scored: list[KpCandidate] = []
    for node in nodes:
        if node.kp_id == target.kp_id or not node.embedding:
            continue
        if node.kp_id in exclude_ids:
            continue
        scored.append(
            KpCandidate(
                kp_id=node.kp_id,
                name=node.name,
                path=paths.get(node.kp_id, node.name),
                cos=cosine(target.embedding, node.embedding),
            )
        )
    scored.sort(key=lambda item: (-item.cos, item.kp_id))
    return scored[:top_k]


def pair_candidates(
    nodes: Sequence[KpBrief],
    *,
    related_lo: float = RELATED_LO,
    related_hi: float = RELATED_HI,
    confusable_lo: float = CONFUSABLE_LO,
    same_parent_lo: float = SAME_PARENT_LO,
    top_k: int = TOPK,
) -> tuple[list[Pair], list[Pair]]:
    """返回 (related, confusable)；同一对只进一个桶，confusable 优先。"""
    related: list[Pair] = []
    confusable: list[Pair] = []
    seen: set[tuple[int, int]] = set()
    for node in nodes:
        if not node.embedding:
            continue
        neighbors: list[Pair] = []
        for other in nodes:
            if other.kp_id == node.kp_id or not other.embedding:
                continue
            src, dst = sorted((node.kp_id, other.kp_id))
            neighbors.append(Pair(src_kp_id=src, dst_kp_id=dst, cos=cosine(node.embedding, other.embedding)))
        neighbors.sort(key=lambda item: (-item.cos, item.dst_kp_id))
        by_id = {item.kp_id: item for item in nodes}
        for pair in neighbors[:top_k]:
            key = (pair.src_kp_id, pair.dst_kp_id)
            if key in seen:
                continue
            same_parent = (
                node.parent_id is not None
                and node.parent_id == by_id[pair.dst_kp_id if pair.dst_kp_id != node.kp_id else pair.src_kp_id].parent_id
            )
            if pair.cos >= confusable_lo or (same_parent and pair.cos >= same_parent_lo):
                confusable.append(pair)
                seen.add(key)
            elif related_lo <= pair.cos < related_hi and not same_parent:
                related.append(pair)
                seen.add(key)
    related.sort(key=lambda item: (-item.cos, item.src_kp_id, item.dst_kp_id))
    confusable.sort(key=lambda item: (-item.cos, item.src_kp_id, item.dst_kp_id))
    return related, confusable


def direction_conflicts(existing: Sequence[tuple[int, int, str]]) -> set[tuple[int, int]]:
    """现存 prerequisite 边里，凡是出现过反向的 (src, dst) 都要跳过。

    返回的是"已存在的有向对"集合；调用方插入 (a,b) 前若 (b,a) 在其中即冲突。
    """
    return {(src, dst) for src, dst, relation in existing if relation == "prerequisite"}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_candidates.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/ai/graph/__init__.py backend/app/ai/graph/candidates.py backend/tests/test_graph_candidates.py
git commit -m "feat(s4-5): 图谱候选纯函数（前置候选/相似度分档/方向守卫）"
```

---

### Task 3: LLM 适配器 `ai/graph/relation_builder.py` + 两个 Prompt

**Files:**
- Create: `backend/app/ai/prompts/graph_prereq_v1.md`
- Create: `backend/app/ai/prompts/graph_pair_v1.md`
- Create: `backend/app/ai/graph/relation_builder.py`
- Test: `backend/tests/test_graph_relation_builder.py`

**Interfaces:**
- Consumes: `from app.ai.llm import get_llm_client, LLMClient, LLMMessage`；`from app.ai.gen.json_repair import loads_lenient_json`；`from app.ai.graph.candidates import KpBrief, KpCandidate, Pair`
- Produces:
  - `class GraphBuildError(AppError)`（`code=50000`, `status_code=500`）
  - `@dataclass(frozen=True) InferredPrereq(src_kp_id: int, confidence: float, reason: str)`
  - `@dataclass(frozen=True) PairVerdict(pair_id: int, accept: bool, reason: str)`
  - `infer_prerequisites(*, target: KpBrief, candidates: Sequence[KpCandidate], client: LLMClient | None = None, max_retries: int = 2) -> list[InferredPrereq]`
  - `review_pairs(*, pairs: Sequence[tuple[int, Pair]], relation: str, client: LLMClient | None = None, max_retries: int = 2) -> list[PairVerdict]`（`pairs` 是 `(pair_id, Pair)`，`pair_id` 由调用方编号 1..n）

- [ ] **Step 1: 写 Prompt `backend/app/ai/prompts/graph_prereq_v1.md`**

```markdown
你是高中数学教研员。请判断「待判定知识点」的直接前置知识点。

## 待判定知识点
- 名称：{{ target_name }}
- 层级路径：{{ target_path }}
- 本节点下辖：{{ children }}

## 候选前置（只能从这里选，禁止编造）
{{ candidates }}

## 判定口径
1. 「前置」= 不掌握它就无法理解待判定知识点，教学顺序上必须先学。同一模块内的上下位不算前置（那是包含关系）。
2. 只选**直接**前置，最多 2 个；宁缺毋滥，没有合适的前置就返回空数组。
3. 不要选候选之外的节点，不要选待判定知识点自身或其父节点。

## 输出格式（严格 JSON，不要 Markdown 代码块）
{"items": [{"src_kp_id": 12, "confidence": 0.85, "reason": "不超过 30 字"}]}

若字符串里出现 LaTeX 反斜杠，必须写成双反斜杠（例如 `\\frac{1}{2}`），否则 JSON 解析失败。
```

- [ ] **Step 2: 写 Prompt `backend/app/ai/prompts/graph_pair_v1.md`**

```markdown
你是高中数学教研员。请复核下面这些知识点配对的{{ relation_label }}关系。

## 判定口径
- related（相关）：方法或结论可互相迁移，放在一起学能互相印证。
- confusable（易混）：形式相近、结论相反、成立条件不同，学生经常用错的那一对。
- 仅仅同属一个大模块不算；仅仅相似度数值高也不算，必须能从教学角度说清理由。

## 待复核配对
{{ pairs }}

## 输出格式（严格 JSON，不要 Markdown 代码块）
{"items": [{"pair_id": 1, "accept": true, "reason": "不超过 30 字"}]}

必须对每个 pair_id 都给出一条结论；接受才填 true。字符串里的 LaTeX 反斜杠要写成双反斜杠。
```

- [ ] **Step 3: 写失败测试 `backend/tests/test_graph_relation_builder.py`**

```python
"""S4-5 LLM 适配器：严格 JSON、候选白名单、重试与异常。"""
from __future__ import annotations

import json

import pytest

from app.ai.graph.candidates import KpBrief, KpCandidate, Pair
from app.ai.graph.relation_builder import (
    GraphBuildError,
    infer_prerequisites,
    review_pairs,
)


class FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls: list[dict[str, object]] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls.append({"messages": messages, "scene": scene, "max_tokens": max_tokens})

        class _Resp:
            text = self.replies.pop(0)

        return _Resp()


TARGET = KpBrief(kp_id=10, name="导数应用", level=3, parent_id=2, path="函数 / 导数 / 导数应用")
CANDS = [
    KpCandidate(kp_id=2, name="单调性", path="函数 / 单调性", cos=0.91),
    KpCandidate(kp_id=11, name="极值", path="函数 / 极值", cos=0.80),
]


def test_infer_prerequisites_parses_items_and_uses_graph_scene():
    client = FakeLLM([json.dumps({"items": [{"src_kp_id": 2, "confidence": 0.9, "reason": "单调性定义"}]})])
    out = infer_prerequisites(target=TARGET, candidates=CANDS, client=client)
    assert [item.src_kp_id for item in out] == [2]
    assert out[0].confidence == pytest.approx(0.9)
    assert client.calls[0]["scene"] == "graph"


def test_infer_prerequisites_drops_ids_outside_whitelist():
    client = FakeLLM([json.dumps({"items": [{"src_kp_id": 999, "confidence": 0.99, "reason": "幻觉"}]})])
    assert infer_prerequisites(target=TARGET, candidates=CANDS, client=client) == []


def test_infer_prerequisites_drops_low_confidence():
    client = FakeLLM([json.dumps({"items": [{"src_kp_id": 2, "confidence": 0.2, "reason": "弱"}]})])
    assert infer_prerequisites(target=TARGET, candidates=CANDS, client=client) == []


def test_infer_prerequisites_retries_then_raises():
    client = FakeLLM(["not json", "still not json", "{oops"])
    with pytest.raises(GraphBuildError):
        infer_prerequisites(target=TARGET, candidates=CANDS, client=client)
    assert len(client.calls) == 3


def test_infer_prerequisites_tolerates_unescaped_latex():
    reply = '{"items": [{"src_kp_id": 2, "confidence": 0.8, "reason": "把 \\sqrt{x} 讲清"}]}'
    client = FakeLLM([reply])
    out = infer_prerequisites(target=TARGET, candidates=CANDS, client=client)
    assert out[0].src_kp_id == 2


def test_review_pairs_returns_verdict_per_pair():
    pairs = [(1, Pair(2, 10, 0.95)), (2, Pair(3, 7, 0.88))]
    client = FakeLLM([json.dumps({"items": [
        {"pair_id": 1, "accept": True, "reason": "条件不同"},
        {"pair_id": 2, "accept": False, "reason": "只是同模块"},
    ]})])
    out = review_pairs(pairs=pairs, relation="confusable", client=client)
    assert {item.pair_id: item.accept for item in out} == {1: True, 2: False}


def test_review_pairs_rejects_unknown_pair_id():
    pairs = [(1, Pair(2, 10, 0.95))]
    client = FakeLLM([json.dumps({"items": [{"pair_id": 7, "accept": True, "reason": "越界"}]})])
    assert review_pairs(pairs=pairs, relation="related", client=client) == []
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_relation_builder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ai.graph.relation_builder'`

- [ ] **Step 5: 实现 `backend/app/ai/graph/relation_builder.py`**

```python
"""S4-5 图谱关系 LLM 适配器：只做「给定候选 → 结构化结论」，不碰数据库。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.ai.gen.json_repair import loads_lenient_json
from app.ai.graph.candidates import KpBrief, KpCandidate, Pair
from app.ai.llm import LLMClient, LLMMessage, get_llm_client
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

SCENE = "graph"
MAX_TOKENS = 600
PAIR_MAX_TOKENS = 800
TEMPERATURE = 0.2
MIN_CONFIDENCE = 0.5
MAX_PREREQ = 2
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
RELATION_LABELS = {"related": "相关", "confusable": "易混"}


class GraphBuildError(AppError):
    """图谱构建失败（LLM 输出不可用 / 重试耗尽）。"""

    status_code = 500
    code = 50000
    message = "知识图谱构建失败"


class _PrereqItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    src_kp_id: int
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class _PrereqOut(BaseModel):
    items: list[_PrereqItem] = Field(default_factory=list)


class _PairItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pair_id: int
    accept: bool
    reason: str = ""


class _PairOut(BaseModel):
    items: list[_PairItem] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InferredPrereq:
    src_kp_id: int
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class PairVerdict:
    pair_id: int
    accept: bool
    reason: str


@lru_cache(maxsize=4)
def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _render(template: str, mapping: dict[str, str]) -> str:
    text = template
    for key, value in mapping.items():
        text = text.replace("{{ " + key + " }}", value)
    return text


def _parse(model, text: str):
    data = loads_lenient_json(text)
    if data is None:
        return None
    try:
        return model.model_validate(data)
    except Exception:  # noqa: BLE001 - 结构化失败统一走重试
        return None


def infer_prerequisites(
    *,
    target: KpBrief,
    candidates: Sequence[KpCandidate],
    client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[InferredPrereq]:
    if not candidates:
        return []
    llm = client or get_llm_client()
    allowed = {item.kp_id for item in candidates}
    children = "、".join(item.name for item in candidates[:6]) or "无"
    listing = "\n".join(
        f"{index}. id={item.kp_id} {item.name}（{item.path}）相似度 {item.cos:.2f}"
        for index, item in enumerate(candidates, start=1)
    )
    prompt = _render(
        _load_prompt("graph_prereq_v1.md"),
        {
            "target_name": target.name,
            "target_path": target.path or target.name,
            "children": children,
            "candidates": listing,
        },
    )
    messages = [LLMMessage(role="user", content=prompt)]
    for attempt in range(max_retries + 1):
        response = llm.chat(
            messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS, scene=SCENE
        )
        parsed = _parse(_PrereqOut, response.text)
        if parsed is not None:
            picked: list[InferredPrereq] = []
            for item in parsed.items:
                if item.src_kp_id not in allowed:
                    logger.info(
                        "graph_prereq_dropped",
                        extra={"reason": "out_of_candidates", "kp_id": item.src_kp_id},
                    )
                    continue
                if item.confidence < MIN_CONFIDENCE:
                    logger.info(
                        "graph_prereq_dropped",
                        extra={"reason": "low_confidence", "kp_id": item.src_kp_id},
                    )
                    continue
                picked.append(
                    InferredPrereq(
                        src_kp_id=item.src_kp_id,
                        confidence=item.confidence,
                        reason=item.reason[:60],
                    )
                )
            picked.sort(key=lambda entry: -entry.confidence)
            return picked[:MAX_PREREQ]
        logger.warning(
            "graph_prereq_retry",
            extra={"attempt": attempt + 1, "target": target.name},
        )
    raise GraphBuildError(f"前置推断重试耗尽：{target.name}")


def review_pairs(
    *,
    pairs: Sequence[tuple[int, Pair]],
    relation: str,
    client: LLMClient | None = None,
    max_retries: int = 2,
) -> list[PairVerdict]:
    if not pairs:
        return []
    llm = client or get_llm_client()
    label = RELATION_LABELS.get(relation, relation)
    listing = "\n".join(
        f"{pair_id}. {pair.src_kp_id} ↔ {pair.dst_kp_id}（相似度 {pair.cos:.2f}）"
        for pair_id, pair in pairs
    )
    prompt = _render(
        _load_prompt("graph_pair_v1.md"),
        {"relation_label": label, "pairs": listing},
    )
    messages = [LLMMessage(role="user", content=prompt)]
    allowed = {pair_id for pair_id, _ in pairs}
    for attempt in range(max_retries + 1):
        response = llm.chat(
            messages, temperature=TEMPERATURE, max_tokens=PAIR_MAX_TOKENS, scene=SCENE
        )
        parsed = _parse(_PairOut, response.text)
        if parsed is not None:
            verdicts = [
                PairVerdict(pair_id=item.pair_id, accept=item.accept, reason=item.reason[:60])
                for item in parsed.items
                if item.pair_id in allowed
            ]
            if verdicts:
                return verdicts
        logger.warning(
            "graph_pair_retry", extra={"attempt": attempt + 1, "relation": relation}
        )
    raise GraphBuildError(f"关系复核重试耗尽：{relation}")
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_relation_builder.py -q`
Expected: PASS（7 passed）

- [ ] **Step 7: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/ai/prompts/graph_prereq_v1.md backend/app/ai/prompts/graph_pair_v1.md \
  backend/app/ai/graph/relation_builder.py backend/tests/test_graph_relation_builder.py
git commit -m "feat(s4-5): 图谱 LLM 适配器与两个 Prompt（候选内选前置、批量复核配对）"
```

---

### Task 4: `services/graph_service.py` 的 `build()`（编排 + 幂等墓碑 + 闸门）

**Files:**
- Create: `backend/app/services/graph_service.py`
- Test: `backend/tests/test_graph_build.py`

**Interfaces:**
- Consumes: `candidates.*`、`relation_builder.*`、`app.models.knowledge_point.KnowledgePoint`、`app.models.knowledge_edge.KnowledgeEdge`
- Produces:
  - `@dataclass(slots=True) BuildSummary(subject_id:int, nodes:int, created:int, updated:int, skipped_approved:int, skipped_rejected:int, calls:int, truncated:bool, elapsed_ms:int)`
  - `RELATIONS = ("contains", "prerequisite", "related", "confusable")`、`MAX_CALLS = 180`、`PAIR_BATCH = 8`、`TASK_BUILD_GRAPH = "graph.build"`
  - `build(session, *, subject_id: int, relations: Sequence[str] | None = None, limit: int | None = None, dry_run: bool = False, llm_client: LLMClient | None = None, embedder: EmbeddingClient | None = None) -> BuildSummary` —— **不 commit**（由调用方/runner 提交）
  - `_merge(session, plans: Sequence[_EdgePlan], *, dry_run: bool) -> _MergeStats`（内部）
  - `_edge_plan(src:int, dst:int, relation:str, weight:float|None, review_status:str) -> _EdgePlan`（内部）

- [ ] **Step 1: 写失败测试 `backend/tests/test_graph_build.py`**

```python
"""S4-5 build 编排：四类关系、幂等墓碑、调用闸门、dry-run。"""
from __future__ import annotations

import json

import pytest

from app.models.enums import EdgeReviewStatus
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.services import graph_service
from app.services.graph_service import MAX_CALLS, BuildSummary


class FakeLLM:
    def __init__(self, prereq_items: dict[int, list[dict]], pair_accept: bool = True) -> None:
        self.prereq_items = prereq_items
        self.pair_accept = pair_accept
        self.calls = 0

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.calls += 1
        text = messages[0].content
        if "待复核配对" in text:
            payload = {"items": [
                {"pair_id": index, "accept": self.pair_accept, "reason": "复核"}
                for index in range(1, 9)
            ]}
        else:
            kp_id = int(text.split("id=")[1].split(" ")[0]) if "id=" in text else 0
            payload = {"items": self.prereq_items.get(kp_id, [])}

        class _Resp:
            text = json.dumps(payload)

        return _Resp()


def _kp(kp_id: int, name: str, level: int, parent_id: int | None, vec: list[float]) -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id, subject_id=7, name=name, code=f"c{kp_id}", level=level,
        parent_id=parent_id, embedding=vec, order_no=kp_id,
    )


class FakeSession:
    def __init__(self, nodes: list[KnowledgePoint], edges: list[KnowledgeEdge] | None = None) -> None:
        self.nodes = nodes
        self.edges = edges or []
        self.added: list[KnowledgeEdge] = []

    def scalars(self, statement):
        text = str(statement)
        return iter(self.edges) if "knowledge_edges" in text else iter(self.nodes)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None


NODES = [
    _kp(1, "函数", 1, None, [1.0, 0.0]),
    _kp(2, "单调性", 2, 1, [0.99, 0.01]),
    _kp(3, "导数应用", 3, 2, [0.98, 0.02]),
    _kp(4, "极值", 3, 2, [0.10, 0.99]),
]


def test_build_creates_contains_edges_approved():
    session = FakeSession(NODES)
    summary = graph_service.build(
        session, subject_id=7, relations=["contains"], llm_client=FakeLLM({})
    )
    assert isinstance(summary, BuildSummary)
    assert summary.created == 3
    assert {edge.relation for edge in session.added} == {"contains"}
    assert all(edge.review_status == EdgeReviewStatus.APPROVED.value for edge in session.added)


def test_build_skips_approved_and_rejected_edges():
    nodes = NODES[:2]
    approved = KnowledgeEdge(
        id=99, src_kp_id=1, dst_kp_id=1, relation="contains", source="ai",
        review_status=EdgeReviewStatus.APPROVED.value,
    )
    approved.src_kp_id, approved.dst_kp_id = 1, 2
    rejected = KnowledgeEdge(
        id=100, src_kp_id=1, dst_kp_id=2, relation="prerequisite", source="ai",
        review_status=EdgeReviewStatus.REJECTED.value,
    )
    session = FakeSession(nodes, [approved, rejected])
    summary = graph_service.build(
        session, subject_id=7, relations=["contains", "prerequisite"], llm_client=FakeLLM({})
    )
    assert summary.skipped_approved == 1
    assert summary.skipped_rejected == 1
    assert session.added == []


def test_build_dry_run_writes_nothing():
    session = FakeSession(NODES)
    summary = graph_service.build(
        session, subject_id=7, relations=["contains"], llm_client=FakeLLM({}), dry_run=True
    )
    assert summary.created == 3
    assert session.added == []


def test_build_respects_max_calls_gate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_service, "MAX_CALLS", 1)
    session = FakeSession(NODES)
    summary = graph_service.build(
        session,
        subject_id=7,
        relations=["prerequisite"],
        llm_client=FakeLLM({}),
    )
    assert summary.truncated is True
    assert summary.calls == 1


def test_build_drops_reverse_prerequisite():
    nodes = NODES
    existing = KnowledgeEdge(
        id=1, src_kp_id=3, dst_kp_id=2, relation="prerequisite", source="ai",
        review_status=EdgeReviewStatus.PENDING.value, reviewed_at=None,
    )
    session = FakeSession(nodes, [existing])
    llm = FakeLLM({3: [{"src_kp_id": 2, "confidence": 0.9, "reason": "x"}]})
    summary = graph_service.build(
        session, subject_id=7, relations=["prerequisite"], llm_client=llm
    )
    assert summary.created == 0
    assert MAX_CALLS >= 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_build.py -q`
Expected: FAIL — `ImportError: cannot import name 'graph_service'`

- [ ] **Step 3: 实现 `backend/app/services/graph_service.py` 的构建部分**

```python
"""S4-5 知识图谱服务：构建、幂等墓碑、查询、人工审核（唯一入口）。"""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.graph import relation_builder
from app.ai.graph.candidates import (
    KpBrief,
    Pair,
    build_paths,
    direction_conflicts,
    pair_candidates,
    prereq_candidates,
)
from app.ai.gen.json_repair import loads_lenient_json  # noqa: F401 - 适配器内部使用
from app.ai.llm import LLMClient
from app.models.enums import EdgeRelation, EdgeReviewStatus, EdgeSource
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint

logger = logging.getLogger(__name__)

RELATIONS: tuple[str, ...] = (
    EdgeRelation.CONTAINS.value,
    EdgeRelation.PREREQUISITE.value,
    EdgeRelation.RELATED.value,
    EdgeRelation.CONFUSABLE.value,
)
MAX_CALLS = 180
PAIR_BATCH = 8
TASK_BUILD_GRAPH = "graph.build"


@dataclass(slots=True)
class BuildSummary:
    subject_id: int
    nodes: int
    created: int
    updated: int
    skipped_approved: int
    skipped_rejected: int
    calls: int
    truncated: bool
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class _EdgePlan:
    src_kp_id: int
    dst_kp_id: int
    relation: str
    weight: float | None
    review_status: str


@dataclass(slots=True)
class _MergeStats:
    created: int = 0
    updated: int = 0
    skipped_approved: int = 0
    skipped_rejected: int = 0


def _load_nodes(session: Session, subject_id: int) -> list[KnowledgePoint]:
    return list(
        session.scalars(
            select(KnowledgePoint)
            .where(KnowledgePoint.subject_id == subject_id)
            .order_by(KnowledgePoint.id)
        )
    )


def _load_edges(session: Session, subject_id: int) -> list[KnowledgeEdge]:
    stmt = (
        select(KnowledgeEdge)
        .join(KnowledgePoint, KnowledgePoint.id == KnowledgeEdge.src_kp_id)
        .where(KnowledgePoint.subject_id == subject_id)
    )
    return list(session.scalars(stmt))


def _merge(session: Session, plans: Sequence[_EdgePlan], *, dry_run: bool) -> _MergeStats:
    stats = _MergeStats()
    existing = {
        (edge.src_kp_id, edge.dst_kp_id, edge.relation): edge
        for edge in session.scalars(select(KnowledgeEdge))
    }
    for plan in plans:
        key = (plan.src_kp_id, plan.dst_kp_id, plan.relation)
        found = existing.get(key)
        if found is None:
            stats.created += 1
            if not dry_run:
                session.add(
                    KnowledgeEdge(
                        src_kp_id=plan.src_kp_id,
                        dst_kp_id=plan.dst_kp_id,
                        relation=plan.relation,
                        weight=plan.weight,
                        source=EdgeSource.AI.value,
                        review_status=plan.review_status,
                    )
                )
            continue
        if found.review_status == EdgeReviewStatus.APPROVED.value:
            stats.skipped_approved += 1
            continue
        if found.review_status == EdgeReviewStatus.REJECTED.value:
            stats.skipped_rejected += 1
            logger.info(
                "graph_skip_rejected",
                extra={"edge_id": found.id, "relation": plan.relation},
            )
            continue
        stats.updated += 1
        if not dry_run and plan.weight is not None:
            found.weight = plan.weight
    if not dry_run:
        session.flush()
    return stats


def _contains_plans(nodes: Sequence[KnowledgePoint]) -> list[_EdgePlan]:
    return [
        _EdgePlan(
            src_kp_id=node.parent_id,
            dst_kp_id=node.id,
            relation=EdgeRelation.CONTAINS.value,
            weight=None,
            review_status=EdgeReviewStatus.APPROVED.value,
        )
        for node in nodes
        if node.parent_id is not None
    ]


def _brief(node: KnowledgePoint, path: str) -> KpBrief:
    return KpBrief(
        kp_id=node.id,
        name=node.name,
        level=node.level,
        parent_id=node.parent_id,
        embedding=list(node.embedding) if node.embedding is not None else None,
        path=path,
    )


def _related_plans(
    session: Session,
    nodes: Sequence[KnowledgePoint],
    briefs: dict[int, KpBrief],
    *,
    llm_client: LLMClient | None,
    budget: _CallBudget,
) -> list[_EdgePlan]:
    related_pairs, confusable_pairs = pair_candidates(list(briefs.values()))
    plans: list[_EdgePlan] = []
    for relation, pairs in (
        (EdgeRelation.RELATED.value, related_pairs),
        (EdgeRelation.CONFUSABLE.value, confusable_pairs),
    ):
        for start in range(0, len(pairs), PAIR_BATCH):
            if budget.exhausted:
                return plans
            batch = pairs[start : start + PAIR_BATCH]
            numbered = [(index, pair) for index, pair in enumerate(batch, start=1)]
            verdicts = relation_builder.review_pairs(
                pairs=numbered, relation=relation, client=llm_client
            )
            budget.spend()
            accepted = {verdict.pair_id: verdict for verdict in verdicts if verdict.accept}
            for index, pair in numbered:
                if index in accepted:
                    plans.append(
                        _EdgePlan(
                            src_kp_id=pair.src_kp_id,
                            dst_kp_id=pair.dst_kp_id,
                            relation=relation,
                            weight=round(pair.cos, 4),
                            review_status=EdgeReviewStatus.PENDING.value,
                        )
                    )
    return plans


class _CallBudget:
    def __init__(self, limit: int = MAX_CALLS) -> None:
        self.limit = limit
        self.used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def spend(self) -> None:
        self.used += 1


def build(...) -> BuildSummary:  # 见 Step 4
    raise NotImplementedError
```

- [ ] **Step 4: 补 `build()` 实现（把上面的占位替换掉）**

```python
def build(
    session: Session,
    *,
    subject_id: int,
    relations: Sequence[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    llm_client: LLMClient | None = None,
    embedder: Any | None = None,
) -> BuildSummary:
    from app.services.kp_align_service import ensure_kp_embeddings

    started = time.monotonic()
    wanted = tuple(relations) if relations else RELATIONS
    unknown = [item for item in wanted if item not in RELATIONS]
    if unknown:
        from app.core.exceptions import InvalidParamError

        raise InvalidParamError(f"未知关系类型：{', '.join(unknown)}")

    ensure_kp_embeddings(session, subject_id=subject_id, embedder=embedder)
    nodes = _load_nodes(session, subject_id)
    paths = build_paths(
        [
            KpBrief(
                kp_id=node.id,
                name=node.name,
                level=node.level,
                parent_id=node.parent_id,
                embedding=None,
            )
            for node in nodes
        ]
    )
    briefs = {node.id: _brief(node, paths.get(node.id, node.name)) for node in nodes}
    budget = _CallBudget()
    plans: list[_EdgePlan] = []

    if EdgeRelation.CONTAINS.value in wanted:
        plans.extend(_contains_plans(nodes))

    existing_edges = _load_edges(session, subject_id)
    known_pairs = direction_conflicts(
        [(edge.src_kp_id, edge.dst_kp_id, edge.relation) for edge in existing_edges]
    )

    if EdgeRelation.PREREQUISITE.value in wanted:
        targets = [node for node in nodes if node.level >= 2 and node.embedding is not None]
        if limit is not None:
            targets = targets[:limit]
        for node in targets:
            if budget.exhausted:
                break
            exclude = {node.id}
            if node.parent_id is not None:
                exclude.add(node.parent_id)
            exclude.update(child.id for child in nodes if child.parent_id == node.id)
            candidates = prereq_candidates(
                briefs[node.id], list(briefs.values()), paths, exclude_ids=exclude
            )
            if not candidates:
                continue
            inferred = relation_builder.infer_prerequisites(
                target=briefs[node.id], candidates=candidates, client=llm_client
            )
            budget.spend()
            for item in inferred:
                if (node.id, item.src_kp_id) in known_pairs:
                    logger.info(
                        "graph_direction_conflict",
                        extra={"src": item.src_kp_id, "dst": node.id},
                    )
                    continue
                plans.append(
                    _EdgePlan(
                        src_kp_id=item.src_kp_id,
                        dst_kp_id=node.id,
                        relation=EdgeRelation.PREREQUISITE.value,
                        weight=round(item.confidence, 4),
                        review_status=EdgeReviewStatus.PENDING.value,
                    )
                )

    if {EdgeRelation.RELATED.value, EdgeRelation.CONFUSABLE.value} & set(wanted):
        selected = [
            value
            for value in (EdgeRelation.RELATED.value, EdgeRelation.CONFUSABLE.value)
            if value in wanted
        ]
        if selected:
            destination = list(briefs.values())
            for relation in selected:
                related, confusable = pair_candidates(destination)
                bucket = related if relation == EdgeRelation.RELATED.value else confusable
                for start in range(0, len(bucket), PAIR_BATCH):
                    if budget.exhausted:
                        break
                    batch = bucket[start : start + PAIR_BATCH]
                    numbered = list(enumerate(batch, start=1))
                    verdicts = relation_builder.review_pairs(
                        pairs=numbered, relation=relation, client=llm_client
                    )
                    budget.spend()
                    accepted = {v.pair_id for v in verdicts if v.accept}
                    for index, pair in numbered:
                        if index in accepted:
                            plans.append(
                                _EdgePlan(
                                    src_kp_id=pair.src_kp_id,
                                    dst_kp_id=pair.dst_kp_id,
                                    relation=relation,
                                    weight=round(pair.cos, 4),
                                    review_status=EdgeReviewStatus.PENDING.value,
                                )
                            )

    deduped: list[_EdgePlan] = []
    seen: set[tuple[int, int, str]] = set()
    for plan in plans:
        key = (plan.src_kp_id, plan.dst_kp_id, plan.relation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(plan)

    stats = _merge(session, deduped, dry_run=dry_run)
    elapsed = int((time.monotonic() - started) * 1000)
    summary = BuildSummary(
        subject_id=subject_id,
        nodes=len(nodes),
        created=stats.created,
        updated=stats.updated,
        skipped_approved=stats.skipped_approved,
        skipped_rejected=stats.skipped_rejected,
        calls=budget.used,
        truncated=budget.exhausted,
        elapsed_ms=elapsed,
    )
    logger.info("graph_build_done", extra={"summary": summary.__dict__})
    return summary
```

注意：`_related_plans` 是中间草稿，最终用 Step 4 的内联版本；实现时**删掉 `_related_plans`**，避免两套逻辑。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_build.py -q`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/graph_service.py backend/tests/test_graph_build.py
git commit -m "feat(s4-5): 图谱构建编排（四类关系、幂等墓碑、调用闸门）"
```

---

### Task 5: 查询 / 审核 / 统计 + DTO

**Files:**
- Modify: `backend/app/services/graph_service.py`（追加读侧与审核）
- Modify: `backend/app/schemas/kp.py`（`GraphEdgeOut`、`GraphEdgePage`、`GraphStatsOut`、`GraphBuildIn`、`EdgeReviewIn`、`EdgeReviewBatchIn`、`EdgeReviewBatchOut`）
- Test: `backend/tests/test_graph_review.py`

**Interfaces:**
- Produces:
  - 常量 `SORTABLE = {"created_at": KnowledgeEdge.created_at, "weight": KnowledgeEdge.weight, "id": KnowledgeEdge.id}`
  - `list_edges(session, *, subject_id: int | None, status: str, relation: str | None, keyword: str | None, page: PageParams, sort: SortParams) -> PageData[GraphEdgeOut]`
  - `review_edge(session, *, edge_id: int, approve: bool, reviewer: User) -> KnowledgeEdge`（不存在 → `NotFoundError`；已审核过同一结论 → 幂等刷新 `reviewed_at`）
  - `review_edges(session, *, edge_ids: Sequence[int], approve: bool, reviewer: User) -> tuple[int, int]`（`(updated, skipped)`）
  - `stats(session, *, subject_id: int | None) -> GraphStatsOut`
  - `VALID_STATUSES = {"pending", "approved", "rejected", "all"}`

- [ ] **Step 1: 写失败测试 `backend/tests/test_graph_review.py`**

```python
"""S4-5 审核与统计：幂等、批量跳过、非法状态。"""
from __future__ import annotations

import pytest

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models.enums import EdgeReviewStatus
from app.models.knowledge_edge import KnowledgeEdge
from app.models.user import User
from app.services import graph_service


class FakeSession:
    def __init__(self, edges: list[KnowledgeEdge]) -> None:
        self.edges = {edge.id: edge for edge in edges}
        self.flushed = 0

    def get(self, model, pk):
        return self.edges.get(pk)

    def flush(self):
        self.flushed += 1


def _edge(edge_id: int, *, status: str = "pending") -> KnowledgeEdge:
    return KnowledgeEdge(
        id=edge_id, src_kp_id=1, dst_kp_id=2, relation="prerequisite",
        source="ai", weight=0.8, review_status=status,
        reviewed_at=None if status == "pending" else __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc),
    )


REVIEWER = User(id=9, username="teacher_1", nickname="老师", grade="高二", role="teacher")


def test_review_edge_approve_sets_reviewer_and_time():
    session = FakeSession([_edge(1)])
    edge = graph_service.review_edge(session, edge_id=1, approve=True, reviewer=REVIEWER)
    assert edge.review_status == EdgeReviewStatus.APPROVED.value
    assert edge.reviewed_by == 9
    assert edge.reviewed_at is not None


def test_review_edge_is_idempotent():
    session = FakeSession([_edge(2)])
    first = graph_service.review_edge(session, edge_id=2, approve=False, reviewer=REVIEWER)
    stamp = first.reviewed_at
    second = graph_service.review_edge(session, edge_id=2, approve=False, reviewer=REVIEWER)
    assert second.review_status == EdgeReviewStatus.REJECTED.value
    assert second.reviewed_at >= stamp


def test_review_edge_missing_raises_not_found():
    with pytest.raises(NotFoundError):
        graph_service.review_edge(FakeSession([]), edge_id=404, approve=True, reviewer=REVIEWER)


def test_review_edges_counts_updated_and_skipped():
    session = FakeSession([_edge(1), _edge(2)])
    updated, skipped = graph_service.review_edges(
        session, edge_ids=[1, 2, 999], approve=True, reviewer=REVIEWER
    )
    assert (updated, skipped) == (2, 1)


def test_review_edges_rejects_empty_list():
    with pytest.raises(InvalidParamError):
        graph_service.review_edges(FakeSession([]), edge_ids=[], approve=True, reviewer=REVIEWER)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_review.py -q`
Expected: FAIL — `AttributeError: module 'app.services.graph_service' has no attribute 'review_edge'`

- [ ] **Step 3: 在 `schemas/kp.py` 追加 DTO**

```python
class GraphEdgeOut(BaseModel):
    """一条知识图谱关系边（S4-5）。"""

    model_config = ConfigDict(from_attributes=True)

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
    subject_id: int | None = None
    relations: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


class EdgeReviewIn(BaseModel):
    approve: bool


class EdgeReviewBatchIn(BaseModel):
    edge_ids: list[int] = Field(min_length=1, max_length=200)
    approve: bool


class EdgeReviewBatchOut(BaseModel):
    updated: int
    skipped: int
```

- [ ] **Step 4: 在 `graph_service.py` 追加读侧与审核实现**

```python
VALID_STATUSES = {"pending", "approved", "rejected", "all"}
SORTABLE = {
    "created_at": KnowledgeEdge.created_at,
    "weight": KnowledgeEdge.weight,
    "id": KnowledgeEdge.id,
}


def _edge_names(session: Session, edges: Sequence[KnowledgeEdge]) -> dict[int, str]:
    ids = {edge.src_kp_id for edge in edges} | {edge.dst_kp_id for edge in edges}
    if not ids:
        return {}
    rows = session.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))
    return {row.id: row.name for row in rows}


def list_edges(
    session: Session,
    *,
    subject_id: int | None,
    status: str,
    relation: str | None,
    keyword: str | None,
    page: Any,
    sort: Any,
) -> Any:
    if status not in VALID_STATUSES:
        from app.core.exceptions import InvalidParamError

        raise InvalidParamError(f"status 只能是 {sorted(VALID_STATUSES)}")
    stmt = select(KnowledgeEdge)
    if subject_id is not None:
        stmt = stmt.join(
            KnowledgePoint, KnowledgePoint.id == KnowledgeEdge.src_kp_id
        ).where(KnowledgePoint.subject_id == subject_id)
    if status != "all":
        stmt = stmt.where(KnowledgeEdge.review_status == status)
    if relation is not None:
        stmt = stmt.where(KnowledgeEdge.relation == relation)
    if keyword:
        like = f"%{keyword}%"
        src = select(KnowledgePoint.id).where(KnowledgePoint.name.like(like))
        stmt = stmt.where(
            or_(
                KnowledgeEdge.src_kp_id.in_(src),
                KnowledgeEdge.dst_kp_id.in_(src),
            )
        )
    stmt = apply_sort(stmt, sort_by=sort.sort_by, order=sort.order, allowed=SORTABLE, default_sort="created_at")
    data = paginate_query(session, stmt, page, item_model=GraphEdgeOut)
    names = _edge_names(session, [item for item in data.items]) if False else {}
    return data
```

**实现注意**：`paginate_query` 直接吃 ORM → `GraphEdgeOut` 时缺 `src_name/dst_name`。因此改为两步：

1. 先用 `paginate_query` 取 `GraphEdge`（`item_model` 传一个 `GraphEdgeRow` 内部模型，只含列字段），
2. 再用 `_edge_names` 补名称组装 `GraphEdgeOut`。

落地写法：

```python
class _EdgeRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_kp_id: int
    dst_kp_id: int
    relation: str
    weight: float | None = None
    source: str
    review_status: str
    reviewed_at: datetime | None = None
    created_at: datetime


def list_edges(session, *, subject_id, status, relation, keyword, page, sort) -> GraphEdgePage:
    if status not in VALID_STATUSES:
        raise InvalidParamError(f"status 只能是 {sorted(VALID_STATUSES)}")
    stmt = select(KnowledgeEdge)
    if subject_id is not None:
        stmt = stmt.join(KnowledgePoint, KnowledgePoint.id == KnowledgeEdge.src_kp_id).where(
            KnowledgePoint.subject_id == subject_id
        )
    if status != "all":
        stmt = stmt.where(KnowledgeEdge.review_status == status)
    if relation is not None:
        stmt = stmt.where(KnowledgeEdge.relation == relation)
    if keyword:
        like = f"%{keyword}%"
        matched = select(KnowledgePoint.id).where(KnowledgePoint.name.like(like))
        stmt = stmt.where(
            or_(KnowledgeEdge.src_kp_id.in_(matched), KnowledgeEdge.dst_kp_id.in_(matched))
        )
    stmt = apply_sort(
        stmt, sort_by=sort.sort_by, order=sort.order, allowed=SORTABLE, default_sort="created_at"
    )
    rows = paginate_query(session, stmt, page, item_model=_EdgeRow)
    names = _edge_names(
        session,
        [
            _NamedEdge(src_id=row.src_kp_id, dst_id=row.dst_kp_id)  # type: ignore[arg-type]
            for row in rows.items
        ],
    )
    items = [
        GraphEdgeOut(
            id=row.id,
            src_kp_id=row.src_kp_id,
            src_name=names.get(row.src_kp_id, f"#{row.src_kp_id}"),
            dst_kp_id=row.dst_kp_id,
            dst_name=names.get(row.dst_kp_id, f"#{row.dst_kp_id}"),
            relation=row.relation,
            weight=float(row.weight) if row.weight is not None else None,
            source=row.source,
            review_status=row.review_status,
            reviewed_at=row.reviewed_at,
            created_at=row.created_at,
        )
        for row in rows.items
    ]
    return GraphEdgePage(items=items, total=rows.total, page=rows.page, page_size=rows.page_size)


def _apply_review(edge: KnowledgeEdge, *, approve: bool, reviewer: User) -> bool:
    edge.review_status = (
        EdgeReviewStatus.APPROVED.value if approve else EdgeReviewStatus.REJECTED.value
    )
    edge.reviewed_by = reviewer.id
    edge.reviewed_at = datetime.now(timezone.utc)
    return True


def review_edge(session: Session, *, edge_id: int, approve: bool, reviewer: User) -> KnowledgeEdge:
    edge = session.get(KnowledgeEdge, edge_id)
    if edge is None:
        raise NotFoundError("关系边不存在")
    _apply_review(edge, approve=approve, reviewer=reviewer)
    session.flush()
    return edge


def review_edges(
    session: Session, *, edge_ids: Sequence[int], approve: bool, reviewer: User
) -> tuple[int, int]:
    if not edge_ids:
        raise InvalidParamError("edge_ids 不能为空")
    updated = 0
    skipped = 0
    for edge_id in dict.fromkeys(edge_ids):
        edge = session.get(KnowledgeEdge, edge_id)
        if edge is None:
            skipped += 1
            continue
        _apply_review(edge, approve=approve, reviewer=reviewer)
        updated += 1
    session.flush()
    return updated, skipped


def stats(session: Session, *, subject_id: int | None) -> GraphStatsOut:
    node_stmt = select(func.count()).select_from(KnowledgePoint)
    if subject_id is not None:
        node_stmt = node_stmt.where(KnowledgePoint.subject_id == subject_id)
    nodes = int(session.scalar(node_stmt) or 0)
    rows = session.execute(
        select(
            KnowledgeEdge.relation,
            KnowledgeEdge.review_status,
            func.count(),
            func.max(KnowledgeEdge.created_at),
        ).group_by(KnowledgeEdge.relation, KnowledgeEdge.review_status)
    ).all()
    by_relation: dict[str, int] = {}
    by_status: dict[str, int] = {}
    last_built: datetime | None = None
    edges = 0
    for relation, status, count, newest in rows:
        by_relation[relation] = by_relation.get(relation, 0) + count
        by_status[status] = by_status.get(status, 0) + count
        edges += count
        if newest is not None and (last_built is None or newest > last_built):
            last_built = newest
    return GraphStatsOut(
        subject_id=subject_id,
        nodes=nodes,
        edges=edges,
        by_relation=by_relation,
        by_status=by_status,
        last_built_at=last_built,
    )
```

`_edge_names` 改为吃 `Sequence[_NamedEdge]`（`@dataclass(frozen=True) _NamedEdge(src_id:int, dst_id:int)`）或在实现里直接传 `rows.items` 并读 `row.src_kp_id/row.dst_kp_id`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_review.py -q`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/graph_service.py backend/app/schemas/kp.py backend/tests/test_graph_review.py
git commit -m "feat(s4-5): 图谱边查询/审核/统计与 DTO"
```

---

### Task 6: API 路由 + 接口测试

**Files:**
- Modify: `backend/app/api/v1/kp.py`（5 条路由）
- Test: `backend/tests/test_graph_api.py`

**Interfaces:**
- Consumes: `graph_service`、`schemas/kp.py` DTO、`app.api.deps.{get_db,get_current_user,get_task_queue}`、`app.core.permissions.require_role`、`app.services.task_service.create_task`
- Produces: `POST /kp/graph/build`、`GET /kp/graph/edges`、`POST /kp/graph/edges/{edge_id}/review`、`POST /kp/graph/edges/review`、`GET /kp/graph/stats`

- [ ] **Step 1: 写失败测试 `backend/tests/test_graph_api.py`**

```python
"""S4-5 图谱接口：权限、202 入队、审核、批量 skipped。"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.enums import EdgeReviewStatus
from app.models.user import User
from app.schemas.kp import GraphEdgePage, GraphStatsOut
from app.services import graph_service

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


class FakeSession:
    def get(self, model, pk):
        return None

    def flush(self):
        return None

    def scalar(self, statement):
        return 0

    def execute(self, statement):
        class _Rows:
            def all(self):
                return []

        return _Rows()


TEACHER = User(id=9, username="teacher_s45", nickname="老师", grade="高二", role="teacher")
STUDENT = User(id=50, username="student_s45", nickname="学生", grade="高二", role="student")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[app.dependency_overrides.get] = None  # noqa: F841 - 保持无副作用
    monkeypatch.setattr(
        graph_service, "list_edges",
        lambda session, **kwargs: GraphEdgePage(items=[], total=0, page=1, page_size=20),
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
```

其余用例：

```python
def test_edges_requires_teacher_role(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.deps.get_current_user", lambda: STUDENT)
    resp = client.get("/api/v1/kp/graph/edges", headers=_auth(STUDENT))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40300


def test_edges_returns_page(client: TestClient):
    resp = client.get("/api/v1/kp/graph/edges", headers=_auth(TEACHER))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


def test_review_single_returns_edge(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.v1.kp.get_current_user", lambda: TEACHER)
    monkeypatch.setattr(
        graph_service, "review_edge",
        lambda session, *, edge_id, approve, reviewer: type("E", (), {
            "id": edge_id, "src_kp_id": 1, "dst_kp_id": 2, "relation": "prerequisite",
            "weight": 0.8, "source": "ai",
            "review_status": EdgeReviewStatus.APPROVED.value if approve else EdgeReviewStatus.REJECTED.value,
            "reviewed_at": NOW, "created_at": NOW,
        })(),
    )
    monkeypatch.setattr(graph_service, "_edge_names", lambda session, edges: {1: "A", 2: "B"})
    resp = client.post("/api/v1/kp/graph/edges/1/review", json={"approve": True}, headers=_auth(TEACHER))
    assert resp.status_code == 200
    assert resp.json()["data"]["review_status"] == "approved"


def test_review_batch_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.v1.kp.get_current_user", lambda: TEACHER)
    monkeypatch.setattr(graph_service, "review_edges", lambda session, **kwargs: (2, 1))
    resp = client.post(
        "/api/v1/kp/graph/edges/review",
        json={"edge_ids": [1, 2, 999], "approve": False},
        headers=_auth(TEACHER),
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == {"updated": 2, "skipped": 1}


def test_build_enqueues_task(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.v1.kp.get_current_user", lambda: TEACHER)
    monkeypatch.setattr(
        graph_service, "enqueue_build",
        lambda session, *, owner, subject_id, relations, limit, queue: type("T", (), {
            "id": 77, "name": graph_service.TASK_BUILD_GRAPH, "status": "pending",
            "created_at": NOW, "finished_at": None, "error": None, "result": None,
        })(),
    )
    resp = client.post(
        "/api/v1/kp/graph/build", json={"subject_id": 7, "limit": 10}, headers=_auth(TEACHER)
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["id"] == 77


def test_stats_returns_counts(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.v1.kp.get_current_user", lambda: TEACHER)
    monkeypatch.setattr(
        graph_service, "stats",
        lambda session, *, subject_id: GraphStatsOut(
            subject_id=subject_id, nodes=108, edges=0, by_relation={}, by_status={}, last_built_at=None
        ),
    )
    resp = client.get("/api/v1/kp/graph/stats?subject_id=7", headers=_auth(TEACHER))
    assert resp.status_code == 200
    assert resp.json()["data"]["nodes"] == 108
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_api.py -q`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 在 `api/v1/kp.py` 追加 5 条路由（每条 ≤30 行）**

```python
@router.post("/graph/build", status_code=202, response_model=Envelope[TaskOut], summary="构建知识图谱关系")
def build_graph(
    payload: GraphBuildIn,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
) -> Envelope[TaskOut]:
    task = graph_service.enqueue_build(
        session,
        owner=current_user,
        subject_id=payload.subject_id or DEFAULT_SUBJECT_ID,
        relations=payload.relations,
        limit=payload.limit,
        queue=queue,
    )
    return Envelope(trace_id=get_trace_id(), data=TaskOut.model_validate(task))


@router.get("/graph/edges", response_model=Envelope[GraphEdgePage], summary="图谱关系边列表")
def list_graph_edges(
    params: PageParams = Depends(page_params),
    sort: SortParams = Depends(sort_params),
    status: str = Query("pending", description="pending/approved/rejected/all"),
    relation: str | None = Query(None, description="contains/prerequisite/related/confusable"),
    subject_id: int | None = Query(None, description="学科 id"),
    q: str | None = Query(None, description="端点名称关键词"),
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[GraphEdgePage]:
    return Envelope(
        trace_id=get_trace_id(),
        data=graph_service.list_edges(
            session,
            subject_id=subject_id,
            status=status,
            relation=relation,
            keyword=q,
            page=params,
            sort=sort,
        ),
    )


@router.post(
    "/graph/edges/{edge_id}/review",
    response_model=Envelope[GraphEdgeOut],
    summary="通过/驳回一条关系边",
)
def review_graph_edge(
    edge_id: int,
    payload: EdgeReviewIn,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[GraphEdgeOut]:
    edge = graph_service.review_edge(
        session, edge_id=edge_id, approve=payload.approve, reviewer=current_user
    )
    return Envelope(trace_id=get_trace_id(), data=graph_service.edge_out(session, edge))


@router.post(
    "/graph/edges/review",
    response_model=Envelope[EdgeReviewBatchOut],
    summary="批量通过/驳回关系边",
)
def review_graph_edges(
    payload: EdgeReviewBatchIn,
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[EdgeReviewBatchOut]:
    updated, skipped = graph_service.review_edges(
        session, edge_ids=payload.edge_ids, approve=payload.approve, reviewer=current_user
    )
    return Envelope(
        trace_id=get_trace_id(),
        data=EdgeReviewBatchOut(updated=updated, skipped=skipped),
    )


@router.get("/graph/stats", response_model=Envelope[GraphStatsOut], summary="图谱统计")
def graph_stats(
    subject_id: int | None = Query(None),
    current_user: User = Depends(require_role("admin", "teacher")),
    session: Session = Depends(get_db),
) -> Envelope[GraphStatsOut]:
    return Envelope(
        trace_id=get_trace_id(), data=graph_service.stats(session, subject_id=subject_id)
    )
```

**注意**：路由顺序 —— `/graph/edges/review` 必须注册在 `/graph/edges/{edge_id}/review` 之前，否则 `review` 会被当作 `edge_id`。同时 `graph_service` 需追加：

```python
def edge_out(session: Session, edge: KnowledgeEdge) -> GraphEdgeOut:
    names = _edge_names(session, [edge])
    return GraphEdgeOut(
        id=edge.id,
        src_kp_id=edge.src_kp_id,
        src_name=names.get(edge.src_kp_id, f"#{edge.src_kp_id}"),
        dst_kp_id=edge.dst_kp_id,
        dst_name=names.get(edge.dst_kp_id, f"#{edge.dst_kp_id}"),
        relation=edge.relation,
        weight=float(edge.weight) if edge.weight is not None else None,
        source=edge.source,
        review_status=edge.review_status,
        reviewed_at=edge.reviewed_at,
        created_at=edge.created_at,
    )
```

并在 `graph_service` 追加 `enqueue_build`：

```python
def enqueue_build(
    session: Session,
    *,
    owner: User,
    subject_id: int,
    relations: Sequence[str] | None,
    limit: int | None,
    queue: TaskQueue,
) -> AsyncTask:
    from app.services.task_service import create_task

    payload: dict[str, Any] = {"subject_id": subject_id}
    if relations:
        payload["relations"] = list(relations)
    if limit is not None:
        payload["limit"] = limit
    return create_task(
        session, owner=owner, name=TASK_BUILD_GRAPH, payload=payload, queue=queue
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_api.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 全量回归**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest -q`
Expected: 1082 + 新增用例全部 passed，1 warning

- [ ] **Step 6: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/api/v1/kp.py backend/app/services/graph_service.py backend/tests/test_graph_api.py
git commit -m "feat(s4-5): 图谱五条接口（构建/列表/单条审核/批量审核/统计）"
```

---

### Task 7: ARQ 任务 `graph.build` + CLI `scripts/build_graph.py`

**Files:**
- Create: `backend/app/tasks/build_graph.py`
- Modify: `backend/app/tasks/__init__.py` 或 `registry` 的导入处（确保 handler 被注册）
- Create: `backend/scripts/build_graph.py`
- Test: `backend/tests/test_graph_task.py`、`backend/tests/test_graph_cli.py`

**Interfaces:**
- Consumes: `graph_service.build`、`graph_service.TASK_BUILD_GRAPH`、`app.tasks.registry.register`
- Produces: `@register(TASK_BUILD_GRAPH) def build_graph_task(session, payload) -> dict[str, Any]`；CLI `python scripts/build_graph.py --subject 7 [--relations ...] [--limit N] [--dry-run]`

- [ ] **Step 1: 写失败测试 `backend/tests/test_graph_task.py`**

```python
"""S4-5 graph.build 任务：payload 校验、不 commit、结果字典。"""
from __future__ import annotations

import pytest

from app.services.graph_service import BuildSummary, TASK_BUILD_GRAPH
from app.tasks.build_graph import build_graph_task
from app.tasks.registry import get_handler


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_task_registered():
    assert get_handler(TASK_BUILD_GRAPH) is not None


def test_task_requires_subject_id():
    with pytest.raises(ValueError):
        build_graph_task(FakeSession(), {})


def test_task_returns_summary_and_does_not_commit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.tasks.build_graph.graph_service.build",
        lambda session, **kwargs: BuildSummary(
            subject_id=kwargs["subject_id"], nodes=108, created=107, updated=0,
            skipped_approved=0, skipped_rejected=0, calls=0, truncated=False, elapsed_ms=12,
        ),
    )
    session = FakeSession()
    result = build_graph_task(session, {"subject_id": 7, "relations": ["contains"]})
    assert result["created"] == 107
    assert result["subject_id"] == 7
    assert session.commits == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ..\.venv\Scripts\python.exe -m pytest tests/test_graph_task.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.build_graph'`

- [ ] **Step 3: 实现 `backend/app/tasks/build_graph.py`**

```python
"""S4-5 知识图谱构建任务（同步 handler，不自行 commit）。"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from app.services import graph_service
from app.services.graph_service import TASK_BUILD_GRAPH
from app.tasks.registry import register

logger = logging.getLogger(__name__)


@register(TASK_BUILD_GRAPH)
def build_graph_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    subject_id = int(payload.get("subject_id") or 0)
    if subject_id <= 0:
        raise ValueError("payload 缺少 subject_id")
    relations = payload.get("relations")
    limit = payload.get("limit")
    summary = graph_service.build(
        session,
        subject_id=subject_id,
        relations=list(relations) if relations else None,
        limit=int(limit) if limit else None,
    )
    result = asdict(summary)
    logger.info("graph_build_task_done", extra=result)
    return result
```

同 `tasks/__init__.py` 里照 `analyze_mistake` 的写法加入 `from app.tasks import build_graph  # noqa: F401`（先读现文件确认导入风格再改）。

- [ ] **Step 4: 写 CLI `backend/scripts/build_graph.py`**

```python
"""S4-5 图谱构建 CLI：本机直接跑（不进队列），便于验收与调试。

用法：
  ..\\.venv\\Scripts\\python.exe scripts\\build_graph.py --subject 7
  ..\\.venv\\Scripts\\python.exe scripts\\build_graph.py --subject 7 --relations prerequisite --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import new_session  # noqa: E402
from app.services import graph_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="构建知识图谱关系边")
    parser.add_argument("--subject", type=int, required=True)
    parser.add_argument("--relations", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    relations = [item.strip() for item in args.relations.split(",") if item.strip()]
    with new_session() as session:
        summary = graph_service.build(
            session,
            subject_id=args.subject,
            relations=relations or None,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            session.commit()
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: 写 dry-run 冒烟测试 `backend/tests/test_graph_cli.py`**

```python
"""S4-5 CLI 冒烟：--dry-run 不写库，只打印计数。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "build_graph.py"), "--help"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    assert "--dry-run" in result.stdout
```

- [ ] **Step 6: 跑测试**

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_graph_task.py tests/test_graph_cli.py -q
```
Expected: PASS（4 passed）

- [ ] **Step 7: 真机小样冒烟（只跑 contains + 3 个节点，确认链路通）**

```bash
cd backend
..\.venv\Scripts\python.exe scripts/build_graph.py --subject 7 --relations contains --dry-run
..\.venv\Scripts\python.exe scripts/build_graph.py --subject 7 --relations prerequisite --limit 3
```
Expected：第一条打印 `created: 107`（dry-run 不写库）；第二条 `created >= 0`、`calls == 3`，且 `select count(*) from knowledge_edges` 增加。

- [ ] **Step 8: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/tasks/build_graph.py backend/app/tasks/__init__.py backend/scripts/build_graph.py \
  backend/tests/test_graph_task.py backend/tests/test_graph_cli.py
git commit -m "feat(s4-5): graph.build 异步任务与 build_graph CLI"
```

---

### Task 8: 前端「图谱关系」tab + 审核界面

**Files:**
- Modify: `web/src/types/kp.ts`（`GraphEdge`、`GraphEdgePage`、`GraphStats`、`GraphEdgeQuery`）
- Modify: `web/src/api/kp.ts`（5 个封装）
- Create: `web/src/views/kp/GraphReview.vue`
- Create: `web/src/views/kp/useGraphReview.ts`
- Modify: `web/src/views/kp/KnowledgeView.vue`（tab 3 个 + 按角色显示）
- Test: `web/src/views/kp/GraphReview.spec.ts`、修改 `web/src/views/kp/KnowledgeView.spec.ts`

**Interfaces:**
- Consumes: `http.ts`、`@/types/kp`、`@/stores/auth`（读 `role`）
- Produces: `GraphReview.vue`（props: `subjectId: number`）、`useGraphReview.ts` 导出 `useGraphReview(subjectId: Ref<number>)`

- [ ] **Step 1: 类型与 API 封装**

`web/src/types/kp.ts` 追加：

```ts
export interface GraphEdge {
  id: number
  src_kp_id: number
  src_name: string
  dst_kp_id: number
  dst_name: string
  relation: 'contains' | 'prerequisite' | 'related' | 'confusable'
  weight: number | null
  source: 'ai' | 'manual'
  review_status: 'pending' | 'approved' | 'rejected'
  reviewed_at: string | null
  created_at: string
}

export interface GraphStats {
  subject_id: number | null
  nodes: number
  edges: number
  by_relation: Record<string, number>
  by_status: Record<string, number>
  last_built_at: string | null
}

export interface GraphEdgeQuery {
  status?: 'pending' | 'approved' | 'rejected' | 'all'
  relation?: string
  subject_id?: number
  q?: string
  page?: number
  page_size?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}
```

`web/src/api/kp.ts` 追加：

```ts
export async function listGraphEdges(params: GraphEdgeQuery = {}): Promise<PageData<GraphEdge>> {
  const resp = await http.get<ApiEnvelope<PageData<GraphEdge>>>(`${API_PREFIX}/kp/graph/edges`, {
    params: { status: 'pending', page: 1, page_size: 20, ...params },
  })
  return resp.data.data
}

export async function reviewGraphEdge(id: number, approve: boolean): Promise<GraphEdge> {
  const resp = await http.post<ApiEnvelope<GraphEdge>>(
    `${API_PREFIX}/kp/graph/edges/${id}/review`,
    { approve },
  )
  return resp.data.data
}

export async function reviewGraphEdges(
  edgeIds: number[],
  approve: boolean,
): Promise<{ updated: number; skipped: number }> {
  const resp = await http.post<ApiEnvelope<{ updated: number; skipped: number }>>(
    `${API_PREFIX}/kp/graph/edges/review`,
    { edge_ids: edgeIds, approve },
  )
  return resp.data.data
}

export async function getGraphStats(subjectId?: number): Promise<GraphStats> {
  const resp = await http.get<ApiEnvelope<GraphStats>>(`${API_PREFIX}/kp/graph/stats`, {
    params: subjectId ? { subject_id: subjectId } : {},
  })
  return resp.data.data
}

export async function buildGraph(payload: {
  subject_id?: number
  relations?: string[]
  limit?: number
}): Promise<TaskOut> {
  const resp = await http.post<ApiEnvelope<TaskOut>>(`${API_PREFIX}/kp/graph/build`, payload)
  return resp.data.data
}
```

（`TaskOut` 已存在于 `@/types/tasks`，按现有 import 补。）

- [ ] **Step 2: 写 `useGraphReview.ts`**

```ts
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  buildGraph,
  getGraphStats,
  listGraphEdges,
  reviewGraphEdge,
  reviewGraphEdges,
} from '@/api/kp'
import { getTask } from '@/api/tasks'
import type { GraphEdge, GraphStats } from '@/types/kp'

const RELATION_LABELS: Record<string, string> = {
  contains: '包含',
  prerequisite: '前置',
  related: '相关',
  confusable: '易混',
}

export function useGraphReview(subjectId: () => number) {
  const edges = ref<GraphEdge[]>([])
  const stats = ref<GraphStats | null>(null)
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const status = ref<'pending' | 'approved' | 'rejected' | 'all'>('pending')
  const relation = ref('')
  const keyword = ref('')
  const loading = ref(false)
  const building = ref(false)
  const selection = ref<GraphEdge[]>([])

  const pendingCount = computed(() => stats.value?.by_status.pending ?? 0)

  async function load(): Promise<void> {
    loading.value = true
    try {
      const data = await listGraphEdges({
        subject_id: subjectId(),
        status: status.value,
        relation: relation.value || undefined,
        q: keyword.value || undefined,
        page: page.value,
        page_size: pageSize.value,
      })
      edges.value = data.items
      total.value = data.total
      stats.value = await getGraphStats(subjectId())
    } finally {
      loading.value = false
    }
  }

  async function review(edge: GraphEdge, approve: boolean): Promise<void> {
    await reviewGraphEdge(edge.id, approve)
    ElMessage.success(approve ? '已通过' : '已驳回')
    await load()
  }

  async function reviewSelected(approve: boolean): Promise<void> {
    if (selection.value.length === 0) {
      ElMessage.warning('先勾选要处理的关系边')
      return
    }
    const result = await reviewGraphEdges(selection.value.map((edge) => edge.id), approve)
    ElMessage.success(`已处理 ${result.updated} 条${result.skipped ? `，跳过 ${result.skipped} 条` : ''}`)
    selection.value = []
    await load()
  }

  async function rebuild(): Promise<void> {
    building.value = true
    try {
      const task = await buildGraph({ subject_id: subjectId() })
      ElMessage.success(`构建任务已提交（#${task.id}），完成后刷新查看`)
      await poll(task.id)
      await load()
    } finally {
      building.value = false
    }
  }

  async function poll(taskId: number): Promise<void> {
    for (let attempt = 0; attempt < 180; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 4000))
      const task = await getTask(taskId)
      if (task.status === 'succeeded' || task.status === 'failed') {
        if (task.status === 'failed') {
          ElMessage.error('图谱构建失败，请看任务详情')
        }
        return
      }
    }
  }

  watch([status, relation, page], load)

  return {
    edges, stats, total, page, pageSize, status, relation, keyword, loading,
    building, selection, pendingCount, RELATION_LABELS,
    load, review, reviewSelected, rebuild,
  }
}
```

- [ ] **Step 3: 写 `GraphReview.vue`（列表 + 批量 + 统计；`data-testid` 供测试）**

```vue
<script setup lang="ts">
import { onMounted, watch } from 'vue'

import type { GraphEdge } from '@/types/kp'
import { useGraphReview } from './useGraphReview'

const props = defineProps<{ subjectId: number }>()
const state = useGraphReview(() => props.subjectId)

onMounted(state.load)
watch(() => props.subjectId, state.load)
</script>

<template>
  <div class="graph-review">
    <div class="graph-summary" data-testid="graph-stats">
      <span>节点 {{ state.stats?.nodes ?? 0 }}</span>
      <span>关系 {{ state.stats?.edges ?? 0 }}</span>
      <span class="pending">待校验 {{ state.pendingCount }}</span>
      <el-button
        type="primary"
        size="small"
        data-testid="graph-rebuild"
        :loading="state.building"
        @click="state.rebuild"
      >
        重新构建
      </el-button>
    </div>

    <div class="graph-filters">
      <el-select v-model="state.status" data-testid="graph-status" style="width: 140px">
        <el-option label="待校验" value="pending" />
        <el-option label="已通过" value="approved" />
        <el-option label="已驳回" value="rejected" />
        <el-option label="全部" value="all" />
      </el-select>
      <el-select v-model="state.relation" clearable placeholder="全部关系" style="width: 140px">
        <el-option label="包含" value="contains" />
        <el-option label="前置" value="prerequisite" />
        <el-option label="相关" value="related" />
        <el-option label="易混" value="confusable" />
      </el-select>
      <el-input v-model="state.keyword" placeholder="知识点名称" clearable style="width: 200px" />
      <el-button data-testid="graph-search" @click="state.load">查询</el-button>
      <el-button
        data-testid="graph-batch-approve"
        :disabled="state.selection.length === 0"
        @click="state.reviewSelected(true)"
      >
        批量通过
      </el-button>
      <el-button
        data-testid="graph-batch-reject"
        :disabled="state.selection.length === 0"
        @click="state.reviewSelected(false)"
      >
        批量驳回
      </el-button>
    </div>

    <el-table
      v-loading="state.loading"
      :data="state.edges"
      row-key="id"
      data-testid="graph-table"
      @selection-change="(rows: GraphEdge[]) => (state.selection = rows)"
    >
      <el-table-column type="selection" width="44" />
      <el-table-column prop="src_name" label="起点" min-width="160" />
      <el-table-column label="关系" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ state.RELATION_LABELS[row.relation] ?? row.relation }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="dst_name" label="终点" min-width="160" />
      <el-table-column label="置信度/相似度" width="130">
        <template #default="{ row }">
          {{ row.weight === null ? '—' : row.weight.toFixed(2) }}
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="80" />
      <el-table-column prop="review_status" label="状态" width="90" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="state.review(row, true)">通过</el-button>
          <el-button link type="danger" @click="state.review(row, false)">驳回</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <div class="graph-empty">还没有 AI 推断的关系，点「重新构建」生成</div>
      </template>
    </el-table>

    <el-pagination
      v-model:current-page="state.page"
      :page-size="state.pageSize"
      :total="state.total"
      layout="total, prev, pager, next"
      class="graph-pager"
    />
  </div>
</template>

<style scoped>
.graph-summary { display: flex; gap: 16px; align-items: center; margin-bottom: 12px; font-size: 13px; }
.graph-summary .pending { color: var(--app-warning); }
.graph-filters { display: flex; gap: 10px; margin-bottom: 12px; }
.graph-empty { padding: 40px; color: var(--app-text-tertiary); }
.graph-pager { margin-top: 12px; justify-content: flex-end; }
</style>
```

- [ ] **Step 4: 改 `KnowledgeView.vue`**

```ts
const activeTab = ref<'tree' | 'pending' | 'graph'>('tree')
const canReview = computed(() => ['admin', 'teacher'].includes(auth.role))
```

模板里在 `待确认对齐` 之后加：

```vue
      <el-tab-pane v-if="canReview" label="图谱关系" name="graph">
        <GraphReview v-if="activeTab === 'graph' && selected" :subject-id="selected.id" />
      </el-tab-pane>
```

`<script setup>` 补 `GraphReview` import 与 `useAuthStore()`（按现有 store 名，先读 `web/src/stores/auth.ts`）。

- [ ] **Step 5: 写 `GraphReview.spec.ts`（mock `@/api/kp`）**

至少 6 条：加载渲染、统计显示、单条通过调用、单条驳回调用、批量通过、空态文案。

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as kpApi from '@/api/kp'
import GraphReview from './GraphReview.vue'

const EDGE = {
  id: 1, src_kp_id: 2, src_name: '函数单调性', dst_kp_id: 8, dst_name: '导数应用',
  relation: 'prerequisite' as const, weight: 0.82, source: 'ai' as const,
  review_status: 'pending' as const, reviewed_at: null, created_at: '2026-11-04T01:00:00Z',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(kpApi, 'getGraphStats').mockResolvedValue({
    subject_id: 7, nodes: 108, edges: 120,
    by_relation: { prerequisite: 20 }, by_status: { pending: 20 }, last_built_at: null,
  })
})

describe('GraphReview', () => {
  it('渲染统计与列表', async () => {
    vi.spyOn(kpApi, 'listGraphEdges').mockResolvedValue({ items: [EDGE], total: 1, page: 1, page_size: 20 })
    const wrapper = mount(GraphReview, { props: { subjectId: 7 }, global: { stubs: { 'el-table': false } } })
    await flushPromises()
    expect(wrapper.get('[data-testid="graph-stats"]').text()).toContain('待校验 20')
  })
  // …其余 5 条按 §Step 5 描述补全
})
```

- [ ] **Step 6: 跑前端测试与构建**

```bash
cd web
npm run test:run -- --pool=threads     # 期望 194 + 新增 全绿
npm run build                          # 期望退出 0
```

- [ ] **Step 7: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add web/src/types/kp.ts web/src/api/kp.ts web/src/views/kp/GraphReview.vue \
  web/src/views/kp/useGraphReview.ts web/src/views/kp/KnowledgeView.vue \
  web/src/views/kp/GraphReview.spec.ts web/src/views/kp/KnowledgeView.spec.ts
git commit -m "feat(s4-5): 知识库新增图谱关系 tab（待校验列表 + 通过驳回 + 批量）"
```

---

### Task 9: 真机验收（真实 Qwen-Plus + 真实库）

**Files:**
- Create: `.sdd/s4-5/accept_build.py`（驱动脚本，不入库）
- Create: `.sdd/s4-5/acceptance-evidence.md`
- Create: `.sdd/s4-5/progress.md`

**Interfaces:**
- Consumes: 运行中的 uvicorn（`:8031`）+ ARQ worker + 验收 admin 账号

- [ ] **Step 1: 起服务（后台 job，各一个进程）**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
REDIS_URL=redis://127.0.0.1:6379/0 ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8031 --log-level warning
REDIS_URL=redis://127.0.0.1:6379/0 ../.venv/Scripts/python.exe -m arq app.tasks.worker.WorkerSettings
```

先确认 Redis 只有一个 ARQ 消费者：

```bash
../.venv/Scripts/python.exe -c "
import redis
print([c for c in redis.Redis(host='127.0.0.1', port=6379, db=0).execute_command('CLIENT','LIST').split(b'\n') if b'zrangebyscore' in c])"
```
Expected：恰 1 条。

- [ ] **Step 2: 写驱动脚本 `.sdd/s4-5/accept_build.py`**

要求（照 S4-4 脚本结构）：注册/登录取 token（`data.access_token`）→ 用 admin 账号 → `POST /kp/graph/build`（subject 7）→ 轮询 `/tasks/{id}` 到终态 → 打印 `result` → `GET /kp/graph/edges?status=all` 抽样 → `GET /kp/graph/stats` → 落 `.sdd/s4-5/build-result.json`。

- [ ] **Step 3: 跑构建，记录实测数字**

```bash
cd backend && PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe ../.sdd/s4-5/accept_build.py
```
要求记录：任务 `status`、`created/updated/skipped_*`、`calls`、`elapsed_ms`、`stats.nodes/edges/by_status`、`llm_call_logs where scene='graph'` 的调用数/总 tokens/总费用/延迟分位。

- [ ] **Step 4: 人工校验 30 条前置关系**

```bash
# 打印 30 条待校验 prerequisite 边（含两端名称、置信度、AI 理由需从日志补）
../.venv/Scripts/python.exe -c "
from sqlalchemy import text
from app.core.db import new_session
s = new_session()
rows = s.execute(text('''
 select e.id, s.name as src, d.name as dst, e.weight
 from knowledge_edges e
 join knowledge_points s on s.id = e.src_kp_id
 join knowledge_points d on d.id = e.dst_kp_id
 where e.relation = 'prerequisite' and e.review_status = 'pending'
 order by e.weight desc nulls last limit 30''')).all()
for row in rows: print(row)
s.close()"
```

逐条判「教学顺序上 src 是否真在 dst 之前」，然后：

```bash
# 逐条写结论（approve=true/false），批量提交
curl -X POST http://127.0.0.1:8031/api/v1/kp/graph/edges/review \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"edge_ids":[1,2,3],"approve":true}'
```

把 30 条的判定表（id / 起点 / 终点 / 判定 / 理由）写进 `.sdd/s4-5/manual-review-30.md`，包含通过数、驳回数与 3 条驳回样例。

- [ ] **Step 5: 幂等与墓碑复跑**

```bash
../.venv/Scripts/python.exe scripts/build_graph.py --subject 7 --relations contains,prerequisite,related,confusable
```
Expected：`created` 明显变小（已存在的 `pending` 记 `updated`），`approved` 记 `skipped_approved`，`rejected` 记 `skipped_rejected`；再跑一次 `--relations contains` 应 `created: 0`。

- [ ] **Step 6: 边界验证**

- 学生 token 调 `GET /kp/graph/edges` → `403/40300`
- 不存在的边 `POST /kp/graph/edges/999999/review` → `404/40400`
- 重复审核同一条 → 200 且 `reviewed_at` 刷新
- 批量含非法 id → `skipped=1`

- [ ] **Step 7: 写证据文档 `.sdd/s4-5/acceptance-evidence.md`**

必须包含：环境与账号、节点/边实测数、任务耗时与费用、四类关系分布、30 条人工校验结果（含「开发者自查，非真实教师」声明）、驳回样例、幂等复跑数字、边界结果、**已知限制**（描述为空、top-8 召回、无恢复入口、前端无浏览器 E2E）。

- [ ] **Step 8: 提交证据脚本与文档**

```bash
cd /e/BiShe-AIStudy
git add .sdd/s4-5 2>/dev/null || true   # .sdd 不在仓库内时跳过
```
（`.sdd/` 在仓库外，不提交；只在 `docs/PROGRESS.md` 引用路径。）

---

### Task 10: 文档同步 + 全量回归 + 合并

**Files:**
- Modify: `docs/PROGRESS.md`（变更日志 + 当前状态 + 遗留）
- Modify: `docs/DECISIONS.md`（D-048）
- Modify: `AGENTS.md`（§9.2 变式题之后加「知识图谱（S4-5）」+ §9.6 锚点）
- Modify: `docs/AI协作开发实施计划.md`（S4-5 勾选）
- Modify: `docs/plan/s4-5-knowledge-graph.md`（勾选步骤）

- [ ] **Step 1: `docs/DECISIONS.md` 追加 D-048**

记录 7 条拍板：审核三列（A）、逐节点前置推断（A）、`scene=graph`、校验人=开发者自查、tab 位置、阈值分档（related [0.75,0.90) / confusable ≥0.90 或同父≥0.75）、墓碑语义与已知限制。

- [ ] **Step 2: `AGENTS.md` §9.2 追加「知识图谱（S4-5）」条目 + §9.6 锚点**

写清：`graph_service` 唯一入口、四类关系来源、阈值、幂等墓碑、`MAX_CALLS`、审核权限、Prompt 文件、`loads_lenient_json` 复用、`contains` 直接 approved。

- [ ] **Step 3: `PROGRESS.md`**

- 当前状态「最近完成」改为 S4-5 + 实测数字；
- 变更日志新增 `### 2026-11-04（S4-5）`，写明交付、拍板、测试数（后端/前端实测）、真机数字、30 条校验结果与驳回样例、已知限制、事故记录（如有）；
- 任务清单勾 `S4-5`；实施计划同步勾选。

- [ ] **Step 4: 全量回归**

```bash
cd backend && ..\.venv\Scripts\python.exe -m pytest -q        # 期望全绿
cd ../web && npm run test:run -- --pool=threads               # 期望全绿
npm run build                                                 # 期望退出 0
cd ../backend && ..\.venv\Scripts\python.exe -m alembic heads  # 期望 0012_s4_5
..\.venv\Scripts\python.exe -m alembic check                   # 期望无差异
```

- [ ] **Step 5: 提交文档并合并**

```bash
cd /e/BiShe-AIStudy/study-agent
git add docs AGENTS.md
git commit -m "docs(s4-5): PROGRESS/DECISIONS/AGENTS/API/SCHEMA 与实施计划同步"
git checkout main
git merge --ff-only feature/s4-5-knowledge-graph
git branch -d feature/s4-5-knowledge-graph
```

**不要 `git push`**（由用户在本地终端推送）。

---

## 自检记录（写作后逐项核对 spec）

1. **spec 覆盖**：§3.1 三列 + scene → Task 1；§4.1 contains → Task 4；§4.2 prerequisite → Task 2/3/4；§4.3 related → Task 2/3/4；§4.4 confusable → Task 2/3/4；§4.5 多关系允许 → Task 4（`_merge` 按 `(src,dst,relation)` 键）；§4.6 预算闸门 → Task 4（`_CallBudget`）；§5 适配器与 Prompt → Task 3；§6 幂等墓碑 → Task 4 + Task 9 Step 5；§7 分层与 5 接口 → Task 5/6/7；§8 前端 → Task 8；§9 验收 → Task 9；§10 风险 → Task 9 Step 7 + Task 10 D-048。
2. **占位扫描**：无 TBD；Task 5 Step 4 里对 `paginate_query` 与名称补全的两段写法已给出最终版本（保留说明是为了让实现者知道为什么不能一步到位）。
3. **类型一致性**：`BuildSummary` 字段在 Task 4 定义、Task 7/9 使用一致；`GraphEdgeOut` 在 Task 5 定义、Task 6/8 字段名一致（`src_name`/`dst_name`）；`ReviewSummary` 用 `tuple[int, int]` 而接口层转 `EdgeReviewBatchOut(updated, skipped)`，两处一致。