# S2-10 笔记/文档 → 知识点对齐 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S2-10
- 日期：2026-10-27
- 状态：设计待用户确认（触发 / 队列操作 / LLM 角色 / 验收数据 已按推荐项拍板）
- 上游：S2-9 知识点树（108 节点、`knowledge_points.embedding` 列与 HNSW 已建但为空）、S2-5 `note_kps`、S2-7 任务框架、S2-8 文档笔记
- 下游：S2-14 前端树/对齐 UI、S3 问答按知识点过滤、S4 错题诊断
- 产物：`services/kp_align_service.py`、`ai/align/`（打分/LLM 抽取/prompt）、`tasks/kp_align.py`、`/kp/align/*` 接口、`data/align_demo_notes.json`（验收输入）

## 1. 目标

1. 按方案 6.2 打分：`score = 0.6*cos + 0.3*keyword + 0.1*tree_prior`。
2. ≥0.75 自动关联（`note_kps` 直接落库、`confirmed=true`）；0.55–0.75 进待确认队列（`confirmed=false`）；<0.55 丢弃。
3. LLM 只在**已有知识点候选**内选择，禁止生成新节点名；严格 JSON + Pydantic 校验 + 最多 2 次重试。
4. 笔记创建/更新后自动异步入队 `kp.align`；提供手动重跑接口；解析出的文档笔记在 parse worker 末尾自动入队。
5. 待确认队列：分页列表 + 批量确认 + 批量忽略。
6. 真实 30 条笔记验收，自动关联人工准确率目标 ≥80%。

非目标：新增/修改知识点树（S2-9）、`knowledge_edges` 构建（S4-5）、错题分析（S4-3）、前端页面（S2-14）、对齐结果的历史审计、按学科多模型。

## 2. 范围

### 2.1 做

- `app/ai/align/`：`scoring.py`（纯函数）、`extractor.py`（LLM 候选内选择 + 重试）、`prompts/kp_align_v1.md`。
- `app/services/kp_align_service.py`：KP 向量补全、候选召回、打分、落库、待确认查询/确认/忽略。
- `app/tasks/kp_align.py` + 注册：`kp.align` 任务。
- API：`POST /kp/align/notes/{note_id}`（202）、`GET /kp/align/pending`、`POST /kp/align/confirm`、`POST /kp/align/reject`。
- 自动触发：notes 创建/更新路由入队；`parse_document` 末尾用独立 session 入队。
- `data/align_demo_notes.json`：30 条高中数学主题笔记（验收输入，人工校对预期知识点）。
- 测试：scoring/extractor/service/api/task 约 33 条。
- 文档：API.md §4、SCHEMA.md §4.4 注记、AGENTS §9.2/§9.3/§9.6、D-030、PROGRESS、实施计划、spec/plan 执行记录。

### 2.2 不做

- 不新增迁移：`note_kps` 四列够用；不加 `created_at`（队列按 `note_id desc, kp_id` 稳定排序）。
- 不做对齐历史/审计表；忽略即删除，重跑可能再次出现。
- 不做跨学科候选合并（当前只有 math；按 note.subject_id 过滤，为空则全树）。
- 不做前端；不做 SSE 进度。
- 不自动确认历史待确认项；不回溯已有笔记（除验收脚本外）。
- 不写 `llm_call_logs`（S3-7 才建表），只打结构化日志。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 触发：笔记 create/update 后路由层 `task_service.create_task(kp.align)`；入队失败只记 WARNING，不影响笔记保存 | 对齐是增强能力，不能因 Redis 故障丢笔记 |
| 2 | 手动重跑：`POST /kp/align/notes/{note_id}` 202 + TaskOut，仅笔记所有者（student） | 不阻塞、可重试、复用 S2-7 |
| 3 | 文档笔记：`parse_document` 在文件 `done` commit 之后，用**独立 session** 创建 `kp.align` 任务；失败只记 WARNING | 不把 LLM 延迟塞进解析 job；独立 session 避免 handler 提交主事务（AGENTS §9.2） |
| 4 | KP 向量：`ensure_kp_embeddings` 把同 subject 中 `embedding IS NULL` 的节点按 `路径/名称/描述` 批量编码并写回；每次对齐前调用（已有则跳过） | 108 节点一次补齐，后续零成本；用现有 `embedding` 列与 HNSW |
| 5 | 候选召回：pgvector `cosine_distance(note_vec)` 取 top-10，按 note.subject_id 过滤（空则全树）；无候选直接 0 关联 | 契约“向量检索 top-10”；避免逐节点算相似度 |
| 6 | 关键词分：知识点全名命中=1.0；去掉常见前缀（函数的/数列的/集合的/三角函数的/平面向量的/一元二次/空间）后的核心词（≥2 字）命中=0.6；否则 0 | 树节点名多为“函数的单调性”，笔记常写“单调性”；别名表暂不建 |
| 7 | 树先验：候选任一祖先名出现在笔记 `tags` 或 `title` →1.0；否则候选 level≤2 →0.3；否则 0 | 无“笔记章节”字段，用标签/标题近似“同章节” |
| 8 | LLM：输入笔记摘要 + 候选表（kp_id/name/path/cos/keyword），要求只选候选、输出 `{matches:[{kp_id,confidence,evidence}]}`；`confidence<0.5` 丢弃；`kp_id` 不在候选内丢弃 | 防止自由生成同义节点（任务卡坑） |
| 9 | 最终分仍用 0.6/0.3/0.1 公式，LLM confidence 不参与加权，只做门槛与证据展示 | 保持方案公式可解释、可复现 |
| 10 | 落库：先删该笔记 `source='ai'` 的旧行（自动+待确认），再写新行；`source='manual'`（用户确认过）保留 | 重跑幂等且不覆盖用户确认；确认时把 source 改为 manual |
| 11 | 自动行 `confirmed=true`（系统已确认，不入队）；待确认行 `confirmed=false`；确认接口置 `confirmed=true, source='manual'`；忽略删除 `source='ai' AND confirmed=false` | 队列过滤简单，语义清晰 |
| 12 | LLM 失败（网络/JSON/校验 3 次）→ 抛 `AlignError`，任务失败由 runner 重试；不做“静默降级为纯算法” | 避免未经验证的降级路径；失败可见 |
| 13 | 任务返回统计：`candidates/matched/auto/pending/dropped`，不含正文明细 | 日志与验收可核对 |
| 14 | 待确认列表固定排序 `note_id desc, kp_id`，不分页排序参数 | 队列按笔记聚合查看；避免无时间列的伪排序 |
| 15 | 批量操作上限 100 对；不在本人名下的 note 对计入 skipped，不报 404 | 批量幂等、避免部分失败 |
| 16 | 阈值常量集中在 `scoring.py`：AUTO=0.75、PENDING=0.55、LLM_MIN_CONF=0.5、TOP_K=10 | 验收调参只改一处 |

## 4. 打分与判定（方案 6.2）

```text
cos       = clamp(1 - cosine_distance(kp.embedding, note_vec), 0, 1)
keyword   = 1.0（全名命中）/ 0.6（去前缀核心词命中）/ 0.0
tree_prior= 1.0（祖先名在 tags/title）/ 0.3（level<=2）/ 0.0
score     = 0.6*cos + 0.3*keyword + 0.1*tree_prior
auto: score >= 0.75；pending: 0.55 <= score < 0.75；drop: < 0.55
```

- 候选先由向量召回；LLM 只对候选做“是/否 + 置信度 + 原文证据”。
- LLM 未选中的候选直接丢弃；LLM 选中但 confidence<0.5 丢弃。
- 同一笔记同一 kp 只保留一条（PK 保证）。

## 5. 接口（API.md §4 定稿）

### POST /api/v1/kp/align/notes/{note_id}
- 权限：笔记所有者（student；其他人的笔记 403/40300，不存在/已软删 404/40400）
- 类型：异步任务提交
- 成功：**202** `Envelope[TaskOut]`：`id` / `name`（`kp.align`）/ `status`（`pending`）/ `created_at`
- 错误：`403/40300`；`404/40400`；`500/50000`「任务队列不可用」

### GET /api/v1/kp/align/pending
- 权限：登录用户（仅本人笔记）
- 类型：同步分页
- 入参：`note_id`（可选）/ `page` / `page_size`
- 出参：`Envelope[PageData[PendingAlignOut]]`
  ```json
  {"items": [{"note_id": 3, "note_title": "函数单调性笔记", "kp_id": 12,
              "kp_name": "函数的单调性", "kp_code": "MATH-FUNC-02",
              "confidence": 0.68}], "total": 1, "page": 1, "page_size": 20}
  ```
- 备注：仅 `source='ai' AND confirmed=false` 且笔记未软删；固定排序 `note_id desc, kp_id`
- 错误：`422/42200` 分页越界

### POST /api/v1/kp/align/confirm
- 权限：登录用户（仅本人笔记）
- 入参：`{"items":[{"note_id":3,"kp_id":12}]}`（1–100 对）
- 出参：`Envelope[AlignBatchOut]`：`{"confirmed": 1, "skipped": 0}`
- 备注：把命中行置 `confirmed=true, source='manual'`；不属于本人/不存在的对计入 skipped
- 错误：`422/42200` 空列表/超过 100 对

### POST /api/v1/kp/align/reject
- 权限：登录用户（仅本人笔记）
- 入参：同上
- 出参：`Envelope[AlignBatchOut]`：`{"deleted": 1, "skipped": 0}`
- 备注：仅删除 `source='ai' AND confirmed=false`；已确认/手工行不删
- 错误：`422/42200`

## 6. 组件契约

### ai/align/scoring.py

```python
AUTO_THRESHOLD = 0.75
PENDING_THRESHOLD = 0.55
LLM_MIN_CONFIDENCE = 0.5
TOP_K = 10

@dataclass(frozen=True)
class Candidate:
    kp_id: int; code: str; name: str; path: str; cos: float; keyword: float; prior: float
    @property score -> float

def keyword_score(kp_name: str, text: str) -> float
def tree_prior(level: int, ancestor_names: list[str], tags: list[str], title: str) -> float
def combine(cos: float, keyword: float, prior: float) -> float
def classify(score: float) -> Literal["auto", "pending", "drop"]
```

### ai/align/extractor.py

```python
class AlignError(Exception)
@dataclass(frozen=True)
class LlmMatch: kp_id: int; confidence: float; evidence: str
def extract_matches(*, note_title: str, note_excerpt: str, candidates: list[Candidate],
                    llm_client: LLMClient | None = None, max_retries: int = 2) -> list[LlmMatch]
```
- prompt 从 `app/ai/prompts/kp_align_v1.md` 读取；`StrictUndefined` 渲染。
- 输出 Pydantic `AlignLLMOutput(matches: list[AlignLLMItem])`；`kp_id` 必须 ∈ candidates；越界/重复丢弃。
- 解析/校验失败重试 2 次；仍失败抛 `AlignError`。

### services/kp_align_service.py

```python
@dataclass(frozen=True)
class AlignStats: candidates:int; matched:int; auto:int; pending:int; dropped:int

def ensure_kp_embeddings(session, *, subject_id: int | None,
                         embedder: EmbeddingClient | None = None) -> int
def retrieve_candidates(session, *, note: Note, note_vec: list[float], top_k: int = TOP_K) -> list[Candidate]
def align_note(session, *, note: Note, embedder=None, llm_client=None) -> AlignStats
def list_pending(session, *, viewer: User, params: PageParams, note_id: int | None = None) -> PageData[PendingAlignOut]
def confirm_pairs(session, *, viewer: User, pairs: list[AlignPair]) -> AlignBatchOut
def reject_pairs(session, *, viewer: User, pairs: list[AlignPair]) -> AlignBatchOut
```

实现要点：
- `align_note`：空文本 → 全 0；ensure 向量 → 编码笔记摘要 → 召回 → 计算 keyword/prior（祖先名需一次性加载同 subject 节点建 map）→ LLM → 打分/分类 → 删旧 `source='ai'` 行 → 写新行（`flush`，不 commit）。
- `ensure_kp_embeddings`：一次查询 subject 内 null 向量节点；构造 `路径 名称 描述`；`embedder.encode` 批量；逐行赋值；返回补全数。
- 候选 SQL：`select(KnowledgePoint).where(subject_id==..., embedding.is_not(None)).order_by(KnowledgePoint.embedding.cosine_distance(vec)).limit(top_k)`。
- `list_pending`：`select(NoteKp).join(Note).options(joinedload(NoteKp.note), joinedload(NoteKp.knowledge_point))`，`paginate_query` + Pydantic `AliasPath` 展平；过滤 `confirmed=false, source='ai', confidence>=0.55, confidence<0.75, Note.user_id=viewer.id, deleted_at is null`。
- `confirm_pairs`/`reject_pairs`：先按 `(note_id, kp_id)` 批量取行并 join Note 校验 owner；不匹配计入 skipped；确认置 `confirmed=true, source='manual'`；忽略仅删 `source='ai' and confirmed=false`。

### tasks/kp_align.py

```python
TASK_KP_ALIGN = "kp.align"

@register(TASK_KP_ALIGN)
def kp_align_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    note_id = int(payload.get("note_id") or 0)
    note = session.get(Note, note_id)
    if note is None or note.deleted_at is not None:
        return {"note_id": note_id, "skipped": True}
    stats = align_note(session, note=note)
    return asdict(stats) | {"note_id": note_id}
```
- 不自行 commit；失败让 runner 回滚/重试。

## 7. 自动触发

- `notes.py` `create_note`/`update_note` 成功后：
  ```python
  try: task_service.create_task(session, owner=current_user, name=TASK_KP_ALIGN,
                                payload={"note_id": note.id}, queue=queue)
  except TaskQueueUnavailableError: logger.warning("kp_align_enqueue_failed", ...)
  ```
  新依赖 `queue: TaskQueue = Depends(get_task_queue)`。
- `parse_document.py` 在 `files` 置 `done` 的 commit 之后：
  ```python
  _enqueue_align_task(file)
  ```
  内部用 `get_session_factory()()` 新 session：查 `User`、`Note`（按 user_id+source_file_id），`create_task`，关闭；异常仅 WARNING，不影响解析结果。

## 8. 验收输入（data/align_demo_notes.json）

30 条，结构：
```json
{"notes": [{"key": "func-monotonic", "title": "函数单调性复习",
            "content_md": "……", "expected_codes": ["MATH-FUNC-02"]}]}
```
覆盖：集合与逻辑、函数性质、指数/对数、三角恒等变换、解三角形、数列、立体几何、解析几何（椭圆/双曲线/抛物线）、导数、概率统计、计数原理、向量/复数、不等式。每条 80–250 字，含明确术语与例题；`expected_codes` 为人工判定的一组可接受节点（用于准确率统计，不参与打分）。

## 9. 测试计划（约 33 条）

`tests/test_align_scoring.py`（10）
1. `combine` 0.6/0.3/0.1 权重与边界
2. `classify` 0.75/0.55 边界（含 0.749）
3. `keyword_score` 全名命中=1.0
4. 去前缀核心词命中=0.6（“函数的单调性”→“单调性”）
5. 无命中=0
6. `tree_prior` 祖先名在 tags=1.0
7. 祖先名在 title=1.0
8. level≤2 无标签=0.3
9. level>2 无标签=0
10. `Candidate.score` 与分类联动

`tests/test_align_extractor.py`（8）
1. 合法 JSON → LlmMatch 列表
2. 候选外 kp_id 被丢弃
3. 重复 kp_id 去重
4. confidence 越界（>1/<-1）被夹取/拒绝（按 Pydantic 拒绝）
5. 非法 JSON → 重试后成功
6. 连续 3 次非法 → AlignError
7. prompt 包含候选表与笔记摘要
8. 空候选 → 不调用 LLM，返回 []

`tests/test_align_service.py`（10）
1. `ensure_kp_embeddings` 只补 null 行并调用 encode 一次
2. 无 null → 0 次 encode
3. `retrieve_candidates` 组装 Candidate 并保留 cos
4. `align_note` 空正文 → 全 0 且不删旧行
5. `align_note` 分类落库：auto/pending/drop 计数正确
6. 先删 `source='ai'`、保留 `source='manual'`
7. LLM 未选中候选 → dropped
8. `list_pending` 只返回本人未确认行
9. `confirm_pairs` 置 confirmed/source=manual，非本人 skipped
10. `reject_pairs` 只删 ai+未确认，已确认 skipped

`tests/test_align_api.py`（8）
1. 手动重跑 202 且任务名 `kp.align`
2. 他人笔记 → 403
3. 不存在 → 404
4. pending 列表 200 结构
5. pending 过滤 note_id
6. confirm 200 计数
7. reject 200 计数
8. 空 items → 422

`tests/test_align_task.py`（4）
1. 正常调用返回统计
2. 笔记不存在 → skipped
3. 已软删 → skipped
4. 非法 payload → ValueError

合计 40 条 → 全量 462 + 40 = 502。

## 10. 验收（真实 LLM/Embedding + Postgres + Redis + Worker）

1. pytest 全绿。
2. 起 uvicorn + worker；注册 student；导入 108 知识点（已有）。
3. 用 30 条验收笔记逐条 `POST /notes`（触发自动对齐），轮询 `GET /tasks/{id}` 或直接等待 worker 队列清空；记录成功/失败任务数。
4. `GET /kp/align/pending` 拉全量；统计 `note_kps` 中 `source='ai' AND confirmed=true`（自动）与待确认数量。
5. 人工核对自动关联：对每条自动链接判断 知识点名 与 笔记主题 是否匹配；准确率 = 正确链接 / 自动链接总数，目标 ≥80%；记录错误链接清单。
6. 批量确认 3 条、忽略 2 条 → 校验 DB：confirmed/source 与行数。
7. 手动重跑一条笔记 → 旧 ai 行被替换、manual 行保留。
8. 清理：note_kps/notes/users/async_tasks；保留 knowledge_points 与 subjects（后续卡复用）。pytest 复跑全绿。

## 11. 文档同步

- API.md §4：4 个对齐接口定稿。
- SCHEMA.md §4.4：注记 `confirmed/source` 语义与重跑规则；待确认队列无时间列。
- AGENTS.md §9.2：对齐规则（向量补全、候选内 LLM、固定公式、重跑保留 manual）；§9.3：LLM 结构化输出与 prompt 位置；§9.6：对齐锚点。
- DECISIONS.md D-030。
- PROGRESS.md 状态/清单/遗留/日志；实施计划 S2-10。
- spec/plan 执行记录。

## 12. 已知限制

- 树先验是“标签/标题含祖先名”的近似，不是真实章节定位；效果依赖笔记标签质量。
- 关键词只匹配节点名与去前缀核心词，无别名表；同义表述可能漏召回。
- 自动阈值用原始余弦（非归一化），不同 embedding 模型分数分布不同；换模型需重新校准。
- LLM 失败即任务失败，不做纯算法兜底；无 Key/额度时对齐不可用。
- 待确认无时间列，无法按“最近待确认”排序；忽略后重跑可能再次出现。
- 一次对齐 = 1 次 embedding（首次含 108 节点补全）+ 1 次 LLM；30 条验收约 30 次 LLM 调用。
- 自动行 `confirmed=true` 与用户确认行靠 `source` 区分；无审计历史。
- 文档笔记在 parse 完成后才入队；解析任务失败则不会对齐。
- 并发重跑同一笔记可能竞争删除/插入，PK 冲突时任务失败重试。

## 13. 执行记录（2026-10-27）

- 交付与 plan 一致；4 个接口、`kp.align` 任务、笔记/解析自动触发全部落地。
- 真实验收：30 条笔记 → 30 个任务成功；自动关联 28 条、待确认 8 条；自动链接人工核对 28/28 正确（100%）；覆盖 25/30 条笔记；5 条因最终分 <0.55 未落库。
- 批量确认 3 条、忽略 2 条、手动重跑 1 条均通过；重跑保留 `manual` 行的 pkey 冲突已修复。
- 测试 500 passed；详细数字与不足见 D-030 / PROGRESS。
