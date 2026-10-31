# S3-2 检索服务 — 设计 Spec

- 任务卡：`docs/AI协作开发实施计划.md`「S3-2 检索服务（复用 S1-4/S1-5）」
- 日期：2026-10-31
- 状态：**已批准**（2026-10-31 用户确认；进入 `docs/plan/s3-2-retrieval-service.md` 实现）
- 上游：S1-4 `retrieve_hybrid/retrieve_hybrid_reranked`、S1-5 Rerank、S2-5 笔记模型、S3-1 索引
- 下游：S3-3 Query 改写、S3-5 问答 API（直接调用本服务）、S3-8 前端引用
- 产物：`services/retrieval_service.py`、`schemas/retrieval.py`、`api/v1/retrieval.py`、`scripts/retrieval_bench.py`、retriever scope 扩展、测试

## 1. 目标

1. **把脚本逻辑封装成服务**：S1-4/S1-5 已有 `retrieve_hybrid_reranked()`，但只被 `scripts/` 与 `eval/` 直接调用；S3-2 新增 `services/retrieval_service.py` 作为唯一业务入口，供 `/retrieval/search` 与后续问答链路复用，**不另写检索 SQL**。
2. **真 scope 过滤**：S1-4 目前对 `subject_id/kp_ids` 直接抛 `RetrievalFilterUnavailable`，等于没有过滤。S3-2 在 retriever 内实现 `subject_id / folder / created_at 范围 / chunk_type` 四类过滤，条件全部下推到 SQL。
3. **可调试、可度量**：新增学生检索接口，支持 `rerank` 开关与 `debug` 明细；新增压测脚本，用真实 HTTP 链路测 P95（不含重排）。
4. **不破坏既有链路**：`answer_question`、`scripts/ask.py`、`scripts/retrieval_eval.py`、`eval/run.py` 的调用方式保持可用。

非目标：Query 改写（S3-3）、问答 SSE 与会话落库（S3-5）、Redis 缓存/用量日志（S3-7）、前端页面（S3-8）、新建 notebook 表或迁移、kp/知识点过滤。

## 2. 已确认决策

| # | 决策 | 理由 / 来源 |
|---|---|---|
| 1 | 新增 `POST /api/v1/retrieval/search`（student，同步 JSON） | 用户 2026-10-31 选 A；任务卡要求“接口 P95”，S3-5 复用同一 service |
| 2 | scope 字段定为 `{subject_id?, folder?, start_date?, end_date?, chunk_types?}`，API.md 的 `notebook_id` 改为 `folder` | 用户 2026-10-31 选 A；库里只有 `notes.folder` TEXT，无 notebook 表，不造不存在的 ID |
| 3 | 时间按 `notes.created_at`，`end_date` 含当天 | 用户确认；与“资料收录时间”语义一致，避免 `updated_at` 让老笔记漂移进范围 |
| 4 | `rerank` 请求可传 `true/false`，缺省读配置（默认 true）；`debug` 默认 false，`debug=true` 才返回候选明细 | 用户确认；避免响应体过大、内部细节默认暴露 |
| 5 | P95 口径：20 个固定问题、HTTP 端到端、`rerank=false`、预热 3 次后采样，含 DashScope Embedding；超标如实报告 | 用户确认；同时记录 `embedding_ms/vector_ms/fulltext_ms` 分项 |
| 6 | 文档笔记 `subject_id` 为 NULL 时，`subject_id` 过滤**不命中**这些笔记，不做回填 | 不猜数据；回填需要文件级学科元数据，另卡处理（见 §10） |
| 7 | 检索 SQL 一律 join `notes`（即使无 scope），并加 `notes.user_id` + `deleted_at IS NULL` | 纵深防御：即使 S3-1 清理遗漏，软删笔记也不会被召回 |
| 8 | 空知识库/无命中返回 200 + `hits=[]` | 任务卡明确要求“空知识库返回空列表不报错” |

## 3. 架构与数据流

```
POST /api/v1/retrieval/search
  │  require_role("student")
  ▼
api/v1/retrieval.search()            # ≤30 行：入参 → service → Envelope
  ▼
services/retrieval_service.search_chunks()
  ├─ 参数/scope 校验（date 区间、top_k、query）
  ├─ rerank=false → ai/rag/retriever.retrieve_hybrid(scope=...) → fused[:top_k]
  ├─ rerank=true  → retrieve_hybrid_reranked(scope=...) → reranked
  ├─ 一次 SQL 批量取 notes.title（WHERE user_id + id IN (...)）
  └─ 组装 RetrievalSearchResponse（hit/debug）
```

`retrieve_hybrid()` 与 `retrieve_hybrid_reranked()` 新增可选 `scope: RetrievalScope | None`；两路 SQL 共用 `_scope_conditions()`。

## 4. 数据模型与过滤语义

```python
# backend/app/ai/rag/retriever.py
class RetrievalScope(BaseModel):
    subject_id: int | None = None
    folder: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    chunk_types: list[Literal["question", "note", "formula"]] | None = None
```

- `_scope_conditions(scope, user_id)` 返回条件列表：
  - 恒有：`NoteChunk.user_id == user_id`、`Note.id == NoteChunk.note_id`（join）、`Note.user_id == user_id`、`Note.deleted_at IS NULL`；
  - `subject_id` → `Note.subject_id == subject_id`；
  - `folder` → `Note.folder == folder`（精确匹配，去首尾空白；空串视为未传）；
  - `start_date` → `Note.created_at >= start_date 00:00:00 UTC`；
  - `end_date` → `Note.created_at < (end_date + 1 day) 00:00:00 UTC`（含当天）；
  - `chunk_types` 非空 → `NoteChunk.chunk_type.in_(chunk_types)`。
- 日期转换用 `datetime.combine(d, time.min, tzinfo=timezone.utc)`；DB 列是 `timestamptz`。
- `subject_id`/`folder` 只影响候选集，不改变 RRF/rerank 公式。
- `RetrievalResult` 新增 `embedding_ms`（查询向量耗时），供 debug 与压测归因。

## 5. 服务层

```python
# backend/app/services/retrieval_service.py
def search_chunks(
    session: Session,
    *,
    user_id: int,
    query: str,
    top_k: int | None = None,
    rerank: bool | None = None,
    scope: RetrievalScopeIn | None = None,
    debug: bool = False,
) -> RetrievalSearchResponse
```

- `top_k`：`None` → `settings.retrieval_top_k`（新增，默认 6）；范围 1–20，超出 → `InvalidParamError`。
- `rerank`：`None` → `settings.retrieval_rerank_enabled`（新增，默认 true）。
- 召回：每路 `settings.retrieval_recall_k`（新增，默认 20）。
- rerank=false：`retrieve_hybrid(..., top_k=recall_k, final_k=top_k, scope=...)`，取 `fused[:top_k]`。
- rerank=true：`retrieve_hybrid_reranked(..., top_k=recall_k, rerank_top_k=top_k, scope=...)`，取 `reranked`；rerank 失败由 S1-5 回退为 fused 顺序，`rerank_info.fallback=true`。
- 标题：对 hits/debug 中出现的全部 `note_id` 做一次 `select(Note.id, Note.title)`，按 `user_id` 过滤；查不到标题时为 `None`（不 500）。
- `snippet`：`" ".join(content.split())[:200]`，只用于展示；`content` 返回完整块文本。
- 不写库、不 commit；不改 `answer_question`。

## 6. 接口契约（写入 `docs/API.md` §5）

### 6.1 请求

```json
POST /api/v1/retrieval/search
{
  "query": "函数单调性怎么判断",
  "top_k": 6,
  "rerank": false,
  "debug": false,
  "scope": {
    "subject_id": 7,
    "folder": "函数",
    "start_date": "2026-10-01",
    "end_date": "2026-10-31",
    "chunk_types": ["note", "question"]
  }
}
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `query` | string | 是 | 1–500 字，去除首尾空白后非空 |
| `top_k` | int | 否 | 1–20，缺省 `retrieval_top_k` |
| `rerank` | bool | 否 | 缺省 `retrieval_rerank_enabled` |
| `debug` | bool | 否 | 默认 false |
| `scope.subject_id` | int | 否 | ≥1 |
| `scope.folder` | string | 否 | ≤200 字，精确匹配 |
| `scope.start_date` | date | 否 | `YYYY-MM-DD` |
| `scope.end_date` | date | 否 | 不早于 `start_date` |
| `scope.chunk_types` | string[] | 否 | 取值 `question/note/formula`，去重；`[]` 视为 422 |

`scope` 未知字段 → 422（`extra="forbid"`），防止拼错字段被静默忽略。

### 6.2 响应

```json
{
  "code": 0,
  "message": "ok",
  "trace_id": "...",
  "data": {
    "query": "函数单调性怎么判断",
    "top_k": 6,
    "rerank": false,
    "elapsed_ms": 287,
    "embedding_ms": 245,
    "rerank_info": null,
    "hits": [
      {
        "chunk_id": 25,
        "note_id": 54,
        "note_title": "高中数学笔记-函数与导数",
        "chunk_index": 4,
        "chunk_type": "note",
        "content": "……",
        "snippet": "……",
        "heading_path": "函数/单调性",
        "page_no": 3,
        "rrf_score": 0.0328,
        "rerank_score": null
      }
    ],
    "debug": {
      "tsquery": "函数 | 单调性 | 判断",
      "vector_ms": 4,
      "fulltext_ms": 2,
      "vector": [],
      "fulltext": [],
      "fused": []
    }
  }
}
```

- `debug=null`（未请求）或对象；`debug.vector/fulltext/fused` 为完整候选（每路最多 `recall_k`），字段同 hit（含 `vector_rank/vector_distance/fulltext_rank/fulltext_score/rrf_score/rerank_score`）。
- `rerank_info`（含 `model/candidates/top_k/tokens/latency_ms/cost_yuan/fallback/error`）在开启重排时返回，关闭时为 null。
- 空知识库/无命中：`hits=[]`、`elapsed_ms` 正常、`code=0`。

### 6.3 错误

| 场景 | HTTP / code |
|---|---|
| 未登录 | 401 / 40100 |
| 非 student（teacher/parent/admin 也拒绝） | 403 / 40300 |
| query 空白、top_k 越界、日期倒置、chunk_types 非法 | 422 / 42200 |
| Embedding 不可用（无 Key/网络失败） | 500 / 50000（Global 兜底，不泄露上游正文） |
| Rerank 失败 | 不报错，回退 fused，`rerank_info.fallback=true` |

## 7. 配置（`core/config.py` + `.env.example`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RETRIEVAL_TOP_K` | 6 | 默认返回条数（1–20） |
| `RETRIEVAL_RECALL_K` | 20 | 每路召回数（向量/全文各取 20 后 RRF） |
| `RETRIEVAL_RERANK_ENABLED` | true | 请求未显式传 `rerank` 时的默认值 |

不新增依赖、不新增表/迁移。

## 8. 测试（沿用 S2 测试写法：FakeSession/FakeClient，不触库、不调外部 API）

| 文件 | 覆盖 |
|---|---|
| `tests/test_retriever.py`（改/增） | 删除 `test_rejects_subject_and_kp_filters`；新增 scope SQL 断言：subject、folder、start/end（含 end+1 天）、chunk_types、`deleted_at IS NULL`、`Notes.user_id`；无 scope 仍 join；`embedding_ms` 存在 |
| `tests/test_retrieval_service.py`（新增，约 10） | 空库 → `hits=[]` 不报错；rerank=false 不调 rerank；rerank=true 取 reranked；标题一次批查（`in_`、含 user_id）且缺失不炸；scope 转换；top_k 越界 422；debug 关闭不返回候选；snippet 截断 |
| `tests/test_retrieval_api.py`（新增，约 8） | 401；teacher 403；student 200 字段齐全；debug=true 返回候选；空库 200；422（query 空、top_k=0、日期倒置、chunk_types 空）；`scope` 未知字段 422 |
| 既有 | 564 条保持全绿（只改 `test_retriever.py` 的旧占位用例） |

## 9. 验收（真实 Postgres/Redis/MinIO + 真实 Embedding）

前置：`docker compose -f deploy/docker-compose.dev.yml up -d`；`alembic upgrade head`（本卡无迁移）；起 uvicorn 与 arq worker。

1. **pytest**：全套全绿（预期约 580 条）。
2. **空库**：新注册学生（无笔记）→ 检索任意问题 → 200、`hits=[]`。
3. **scope 过滤**：为验收学生建 1 篇含「题目块 + 笔记块」的笔记（subject=7、folder=函数）→ 等 `index.note` 成功 → 验证：
   - 无 scope 命中；
   - `subject_id=7` 命中；`subject_id=8` 空；
   - `folder="函数"` 命中；`folder="数列"` 空；
   - 创建前日期范围空；覆盖当天命中；
   - `chunk_types=["question"]` 只返回 question 块；`["formula"]` 不返回 note 块。
4. **重排开关**：`rerank=false` 返回 fused 顺序且 `rerank_info=null`；`rerank=true` 返回 `rerank_info`（`fallback` 为 false 时确有分数）。
5. **debug**：`debug=true` 时 `vector/fulltext/fused` 非空，`debug=null` 时无；响应不含其它用户内容。
6. **权限**：匿名 401；teacher 403；student 200。
7. **P95**：`scripts/retrieval_bench.py --username <student> --runs 20 --warmup 3 --no-rerank` 打 HTTP，输出 P50/P95 与 `embedding_ms/vector_ms/fulltext_ms`；P95 < 500ms 为通过，超标如实记录原因。
8. **回归**：`scripts/ask.py` 真实问题仍能命中并回答；`scripts/retrieval_eval.py --user-id <id>` 仍可跑。
9. 实测数字（P95、分项、命中块）原样贴进 plan 执行记录，不造数。

## 10. 已知限制

1. **带 `subject_id` 的检索不命中文档笔记**：S2-8 生成的文档笔记 `subject_id` 为 NULL；需要文件级学科元数据回填，另卡处理。
2. **folder 是自由文本**：没有笔记本表，重命名文件夹等于换 scope；无层级/权限语义。
3. **P95 含外部 Embedding**：实测 DashScope 单次查询 120–265ms（P50 154ms），端到端 P95 229ms；Embedding 抖动时 P95 会贴线，S3-7 加缓存后才能稳定下降。
4. **debug 响应较大**：最多返回 3×20 条完整块文本，仅用于调试，前端不得常开。
5. **kp/知识点过滤未支持**：`note_kps` 有数据，但检索下推需要新 join 与索引评估，另卡。
6. **rerank 失败静默回退**（S1-5 既有行为）：非 debug 调用方只能从 `rerank_info.fallback` 判断。
7. 教师/家长仍不能调用检索接口（与 QA 一致），家长视角需另设计。
## 11. 实施记录（2026-10-31）

- 提交：`89bd774` retriever scope + `embedding_ms`；`9bb5264` schemas/config/service；`274361f` student API；`25831db` bench 脚本；文档提交见 plan。
- 测试：**586 passed, 1 warning**（基线 564 −1 旧 `test_rejects_subject_and_kp_filters` +4 retriever +10 service +9 API）。
- 验收（真实 Postgres/Redis、真实 DashScope Embedding/Rerank，验收笔记 note 81）：
  - 建笔记后 `index.note` succeeded，2 块（note 287、question 288）。
  - 无 scope / subject=7 / folder=函数 / 当天日期范围：各 2 命中；subject=8 / folder=数列 / 创建前日期 / `chunk_types=["formula"]`：各 0 命中；`chunk_types=["question"]`：仅 288。
  - `rerank=true`：`qwen3-rerank`、`fallback=false`、candidates=2、tokens=120、latency=193ms、scores 0.832/0.528；`rerank=false`：`rerank_info=null`。
  - `debug=true`：vector/fulltext/fused 各 2 条，`vector_ms=3`、`fulltext_ms=2`、`embedding_ms=148`。
  - 空库学生：200 + `hits=[]`；匿名 401/40100；teacher 403/40300。
- P95：`retrieval_bench.py --runs 20 --warmup 3 --no-rerank` → wall P50 172ms / **P95 229ms**；server P50 163 / P95 223；embedding P50 154ms；PASS。
- 回归：`ask.py --user-id 28` 引用笔记 #81 两块、refused=否；`retrieval_eval.py --user-id 28` 10 问完成（仅 1 篇笔记，hit@5 2/10）。
- 与 spec 的偏移：验收 Markdown 只切出 note+question 两类（无 formula 块），因此 `["formula"]` 为 0 命中而非“只返回 formula”；不影响过滤语义。P95 首轮冷启动单次 441ms（jieba/连接冷），预热后进入 130–280ms。
