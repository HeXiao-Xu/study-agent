# S4-5 知识图谱关系构建 + 人工校验 —— 设计 spec

- 卡号：S4-5（`docs/AI协作开发实施计划.md`）
- 状态：待用户确认
- 前置：S2-9（知识点树）、S2-10（知识点对齐）、S3-2（检索与向量）、S4-4（AI 生成题）
- 产出：迁移 `0012_s4_5`、`services/graph_service.py`、`ai/graph/relation_builder.py` + Prompt、`tasks/build_graph.py`、`scripts/build_graph.py`、`api/v1/kp.py` 图谱接口、前端「图谱关系」tab

## 1. 背景与目标

知识点树只有层级（`parent_id`），没有「前置 / 相关 / 易混」这些教学关系。方案 5.2 要求四类关系：

| relation | 语义 | 来源 |
|---|---|---|
| `contains` | 父节点包含子节点 | 由树确定性派生 |
| `prerequisite` | A 是 B 的前置（先学 A 再学 B） | LLM 推断 |
| `related` | 强相关、可互相迁移的方法/概念 | 向量相似度筛选 + LLM 复核 |
| `confusable` | 易混淆（形近、结论相反、条件不同） | 向量相似度筛选 + LLM 复核 |

目标：在 subject 7（数学，现 108 节点）上建成**可校验**的关系图——AI 推断的边默认「待校验」，人工通过后才算真相；被驳回的边记墓碑，重跑不再复活。

## 2. 范围

**做**
1. 迁移 `0012_s4_5`：`knowledge_edges` 加审核三列；`llm_call_logs.scene` 白名单加 `graph`。
2. 四类关系的构建流水线（`contains` 派生 + `prerequisite` 逐节点 LLM 推断 + `related`/`confusable` 向量候选 + LLM 复核）。
3. 幂等/可重跑的 CLI（`scripts/build_graph.py`）与异步任务（`graph.build`）。
4. 审核接口（列表/单条/批量通过驳回）+ 统计。
5. 前端知识库页「图谱关系」tab：筛选、列表、通过/驳回、批量操作、来源与置信度展示。
6. 真机验收：108 节点 + ≥150 条边；人工（本卡由开发者用验收 admin 账号代点，如实标注）校验 30 条前置关系。

**不做**
- ECharts 可视化、节点详情侧栏（S4-6）。
- 学生视角的图谱读接口（S4-7 掌握度着色时一并定）。
- 知识点描述补全（当前 108 个 `description` 全空，本卡只用 `name` + 父链 + 子节点名喂 LLM，不做描述生成）。
- 自动定期重建（APScheduler 定时留 S7 阶段）。

## 3. 契约变更（先改契约再写码，§9.1）

### 3.1 SCHEMA.md §3.2 新增三列

| 字段 | 类型 | 可空 | 默认值 | 说明 | 索引 |
|---|---|---|---|---|---|
| review_status | TEXT | 否 | `'pending'` | `pending` / `approved` / `rejected`，§10.17 | `ix_knowledge_edges_review_status` |
| reviewed_by | BIGINT | 是 | — | 审核人 `users.id`；FK ON DELETE SET NULL | — |
| reviewed_at | TIMESTAMPTZ | 是 | — | 最近一次审核时间 | — |

- 约束：`ck_knowledge_edges_review_status`（三值）；`ck_knowledge_edges_reviewed`：`review_status = 'pending'` 时 `reviewed_by`/`reviewed_at` 均为 NULL，否则 `reviewed_at` 非空（`reviewed_by` 允许 NULL，兼容脚本批量通过）。
- 回填：迁移里把所有已存在行置 `approved`（当前 0 行，但保证幂等）；`contains` 派生边一律直接 `approved`。
- 新枚举常量：`EdgeReviewStatus`（`app/models/enums.py`），§10.17 新增值集。
- `llm_call_logs.scene`：CHECK 扩展为 `qa/query_rewrite/kp_align/embed/mistake/gen/graph/agent`（同迁移，`ck_llm_call_logs_scene` 重建）。

### 3.2 API.md 新增 §4.5「知识图谱关系」

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/kp/graph/build` | admin/teacher | 202 + `TaskOut`，异步构建（`graph.build`），body 可选 `{relations:[...], limit:int}` |
| GET | `/api/v1/kp/graph/edges` | admin/teacher | 边列表：`status`（默认 `pending`，可 `all`）、`relation`、`subject_id`、`q`（任一端名称包含）、分页排序 |
| POST | `/api/v1/kp/graph/edges/{edge_id}/review` | admin/teacher | `{approve: bool}` → 200 返回边；幂等（重复审核同一结果不报错，刷新 `reviewed_at`） |
| POST | `/api/v1/kp/graph/edges/review` | admin/teacher | 批量：`{edge_ids:[...], approve: bool}` → 返回 `{updated, skipped}` |
| GET | `/api/v1/kp/graph/stats` | admin/teacher | 节点数、按 relation × review_status 的边计数、待校验数、最近构建时间 |

- 统一 `Envelope`；错误沿用 `404/40400`（边不存在）、`422/42200`（参数非法）、`403/40300`（学生调用）、`500/50000`（队列不可用）。
- 边出参 `GraphEdgeOut`：`id, src{id,name,level}, dst{id,name,level}, relation, weight, source, review_status, reviewed_at, created_at`（名称一次 `IN` 批查，禁止 N+1）。

## 4. 生成策略（核心设计）

### 4.1 `contains`（确定性）

- 对 subject 内每个 `parent_id` 非空的节点，`src=parent_id`、`dst=id`、`relation='contains'`、`source='ai'`、`review_status='approved'`、`weight=NULL`。
- 108 节点 → 107 条；`ON CONFLICT (src,dst,relation) DO NOTHING` 幂等。

### 4.2 `prerequisite`（LLM 逐节点推断，用户拍板 A）

对每个待推断节点 `B`（默认 level ≥ 2，即 107 个；可用 `limit` 限流）：

1. **候选构造**（确定性，禁 N+1）：`B` 的 `name`；`B` 的父链名称（最多 3 层）；`B` 的子节点名称（≤6 个）；知识库中与 `B` **embedding 余弦相似度 top-8 的其它节点**（排除自身、父子、已在 `contains` 里的关系）。
2. **一次 LLM 调用**（`scene="graph"`，`temperature=0.2`，`max_tokens=600`）：让模型在**给定候选 id 白名单内**选 0–2 个直接前置，并给 `confidence`（0–1）与一句理由。
3. **落库**：`src=前置`、`dst=B`（方向统一为「前置 → 后继」）、`relation='prerequisite'`、`weight=confidence`、`source='ai'`、`review_status='pending'`。
   - `confidence < 0.5` 丢弃（与 S2-10 的门禁一致）。
   - 候选外的 id、自己、父子关系一律丢弃。
4. **方向守卫**（确定性）：若已存在反向边 `B → 前置`，则跳过并记 `graph_direction_conflict` 日志，避免「互为前置」。

### 4.3 `related`（向量 0.75–0.90 + LLM 复核）

1. 对同 subject 所有节点两两比较代价 O(n²)；改为**每个节点取 top-8 近邻**，余弦落在 **[0.75, 0.90)** 且不同父、关系非 `contains` 的配对作为候选。
2. 配对规范化：`src_kp_id < dst_kp_id`（无向关系只存一次）。
3. LLM 复核（批量，每批 ≤8 对，`max_tokens=800`）：输出每对 `{pair_id, related: bool, reason}`；只收 `related=true`。
4. 落库：`relation='related'`、`weight=余弦值`、`source='ai'`、`review_status='pending'`。

### 4.4 `confusable`（向量 ≥0.90 + LLM 复核）

1. 候选同 4.3，但余弦 **≥ 0.90** 或（**同一父节点下**且余弦 ≥ 0.75）。
2. 复核 Prompt 明确「易混 = 形近/结论相反/成立条件不同，仅仅相关不算」，`max_tokens=800`。
3. 落库同上，`review_status='pending'`。

### 4.5 同一对节点的多关系

- 允许 `related` 与 `confusable` 同时存在（语义不同），但**同一对节点不允许既 `prerequisite` 又有反向 `prerequisite`**；`confusable` 与 `prerequisite` 不互斥。
- 所有写入走 `ON CONFLICT (src,dst,relation) DO UPDATE`，只更新 `weight/review_status`（**不覆盖已审核结果**，见 §6）。

### 4.6 预算与闸门

- 单次构建硬上限：LLM 调用 ≤ 180 次（`MAX_CALLS`），超限停止并把任务标记 `succeeded` + `truncated=true`（避免一次跑飞）。
- 逐节点推断 108 次 + 复核约 20 次，预计 **¥0.1–0.3**、6–12 分钟。
- 所有调用照常落 `llm_call_logs`（`scene='graph'`）。

## 5. LLM 适配器与 Prompt

- `ai/graph/relation_builder.py`：
  - `PrereqContext`（节点、父链、子节点名、候选列表）→ `infer_prerequisites(ctx, *, llm_client=None)` → `list[InferredPrereq{src_kp_id, confidence, reason}]`
  - `PairReviewContext`（批量配对）→ `review_pairs(ctx, relation, *, llm_client=None)` → `list[PairVerdict{pair_id, accept, reason}]`
  - 严格 JSON + Pydantic + 最多 2 次重试（§5 AI 约束），失败抛 `GraphBuildError`；候选 id 越界一律丢弃。
  - **复用 S4-4 的 `ai/gen/json_repair.py::loads_lenient_json`**（模型输出中文/公式时同样会漏转义反斜杠）。
- Prompt 文件：`ai/prompts/graph_prereq_v1.md`、`ai/prompts/graph_pair_v1.md`。
- `scene="graph"`；模型与 S4-4 相同（`qwen-plus`）。

## 6. 幂等、重跑与墓碑

`services/graph_service.py::build(subject_id, relations, limit)` 语义：

1. `contains`：`DO NOTHING`（永远确定性重算）。
2. `prerequisite`/`related`/`confusable`：
   - 目标键 `(src,dst,relation)` **已存在且 `review_status='approved'`** → 跳过（人工结论优先，不重算、不降级）。
   - 已存在且 `'rejected'` → 跳过并记 `graph_skip_rejected`（**墓碑**：重跑不复活，除非人工在界面「恢复为待校验」，本卡不提供恢复入口，写进已知限制）。
   - 已存在且 `'pending'` → 更新 `weight`（重新推断的置信度/余弦），保持 `pending`。
   - 不存在 → 插入 `pending`。
3. 任务结果 `result`：`{subject_id, nodes, created, updated, skipped, rejected_skipped, calls, elapsed_ms, truncated}`。
4. CLI `scripts/build_graph.py --subject 7 --relations prerequisite,related,confusable,contains [--limit N] [--dry-run]`：`--dry-run` 只打印将写入的计数不落库；非 dry-run 直接调 service（同步执行，便于本机跑）。

## 7. 服务与接口分层

- `services/graph_service.py`（唯一入口）：
  - `build(session, *, subject_id, relations, limit, dry_run=False) -> BuildSummary`
  - `list_edges(session, *, subject_id, status, relation, q, page_params, sort) -> PageData[GraphEdgeOut]`（名称一次 `IN` 批查）
  - `review_edge(session, *, edge_id, approve, reviewer) -> KnowledgeEdge`
  - `review_edges(session, *, edge_ids, approve, reviewer) -> ReviewSummary{updated, skipped}`
  - `stats(session, *, subject_id) -> GraphStatsOut`
  - `enqueue_build(session, *, owner, subject_id, relations, limit, queue) -> AsyncTask`（走 `task_service.create_task`，队列不可用 → `500/50000`）
- `tasks/build_graph.py`：handler `(Session, payload)` **不 commit**，返回 `result`；注册 `TASK_BUILD_GRAPH = "graph.build"`（常量在 service，task 反向导入）。
- 路由 `api/v1/kp.py` 追加 5 条（每条 ≤30 行），权限 `require_role("admin", "teacher")`。
- 事务：一次用例一个事务；`review_*` 单事务。

## 8. 前端（知识库页新增「图谱关系」tab）

- `KnowledgeView.vue`：tab 从 1 个变 2 个（「知识点树」/「图谱关系」），学生不可见（与写接口权限一致；学生进入知识库仍是只读树视图）。
- `views/kp/GraphReview.vue` + `useGraphReview.ts`：
  - 顶部：统计（节点数、待校验/已通过/已驳回计数）、「重新构建」按钮（触发 `POST /kp/graph/build` + 4s 轮询任务）、relation 与 status 筛选。
  - 列表：`el-table`，列 = 起点 / 关系（中文标签 + 颜色 tag）/ 终点 / 置信度或相似度 / 来源 / 状态 / 操作（通过、驳回）；多选 + 批量通过/驳回。
  - 空态：「还没有 AI 推断的关系，点『重新构建』生成」。
  - 错误：`http.ts` 统一弹错，组件只处理局部状态（§9.5）。
- 类型：`web/src/types/kp.ts` 增 `GraphEdge`、`GraphEdgePage`、`GraphStats`；`api/kp.ts` 增 5 个封装。

## 9. 验收口径（真机）

1. 迁移 `0012_s4_5` 上库：三列 + 两条 CHECK + 索引 + `scene` 白名单含 `graph`；`alembic check` 无差异。
2. 真实构建（Qwen-Plus + 真实 PG）：节点 **108**、边 **≥150**（contains 107 + 其余 ≥43），任务 `succeeded`，耗时与调用数、费用落 `llm_call_logs`。
3. **人工校验 30 条前置关系**：由**开发者用验收 admin 账号**逐条通过/驳回（如实标注「开发者自查，非真实教师校验」），记录通过与驳回数量；驳回样例要写进证据文档。
4. 接口边界：学生调用 → `403/40300`；不存在的边 → `404/40400`；重复审核 → 幂等；批量含非法 id → `skipped` 计数。
5. 幂等：`build` 连跑两次，第二次 `created=0`；已 `approved` 的边不被改写；`rejected` 的边不复活。
6. 前端：单测（tab 切换、列表渲染、通过/驳回调用、批量、空态、轮询）+ `npm run build`；**浏览器级 E2E 不做**（本机无 Playwright，§2.1），如实写进证据文档。
7. 回归：后端全量 pytest、前端全量 vitest、`alembic heads` 应为 `0012_s4_5`。

## 10. 风险与已知限制

| 风险 | 处理 |
|---|---|
| LLM 造边（答辩必问） | 全部 AI 边默认 `pending`，只有人工通过才 `approved`；驳回记墓碑不复活；统计里 `pending` 与 `approved` 分开展示 |
| 前置方向错（A→B 写成 B→A） | 反向边守卫 + 人工校验；Prompt 明确「src 是先学、dst 是后学」 |
| 相似度候选漏召 | 每节点 top-8 近邻，非全量；漏掉的边不会报错，属召回限制 |
| 知识点描述为空 | 只用名称/父链/子名喂 LLM，推断精度受限，写进已知限制 |
| 幻觉出候选外的 id | Pydantic 校验 + 白名单过滤，越界丢弃并计数 |
| 构建耗时长（108 次调用） | `MAX_CALLS=180` 闸门 + `truncated` 标记；任务可重跑补齐 |
| 已知限制（不粉饰） | 无「恢复已驳回边」入口；无定期重建；无学生视角读接口；`confusable` 与 `related` 判定边界由模型把握，存在口径可争 |

## 11. 待确认清单

1. 迁移 `0012_s4_5` 加三列 + `scene='graph'`（已定 A）。
2. 前置推断逐节点一次、候选 top-8（已定 A）。
3. 校验人 = 开发者用验收 admin 账号代点，文档标注（已定）。
4. 校验界面 = 知识库页「图谱关系」tab（已定）。
5. 本节其余细节（§4 阈值、§6 墓碑语义、§7 接口形状、§9 验收数字）请一并确认或指出要改的地方。