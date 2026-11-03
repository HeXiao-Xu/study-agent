# S4-3 错因诊断服务 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S4-3（`docs/AI协作开发实施计划.md:671`）
- 方案依据：`docs/个性化学习智能体-毕业设计完整方案.md` §6.3「错题本与 AI 错题分析」
- 日期：2026-11-03
- 状态：设计已逐节确认，待用户评审本文
- 上游：S4-2（`mistakes` / `mistake_analyses` 两表、错题状态机、拍照识别）、S4-1（`questions` / `question_kps`、知识点对齐）、S3-2（`retrieval_service.search_chunks`）、S2-7（异步任务 + runner）、S3-4（Prompt 版本约定，本卡沿用文件型 Prompt）、S0-5（`AppError` 体系）
- 下游：S4-4 变式题生成（读本卡的 `kp_ids` 与错因作为生成条件，写 `similar_questions_json`）、S4-7 掌握度（答错回写）、S4-8 统计看板（`by_cause` 从此有真实数据）、S4-6 图谱前端（前置知识展示）
- 产物：迁移 `0011_s4_3_mistake_analysis.py`、`models/mistake_analysis.py`（两列）、`ai/analyze/{__init__,mistake_analyzer}.py`、`ai/prompts/mistake_analyze_v1.md`、`services/mistake_analysis_service.py`、`tasks/analyze_mistake.py`、`api/v1/mistakes.py`（+1 路由）、`schemas/mistake.py`（DTO 扩展）、前端 `views/mistakes/MistakeDetailView.vue` 诊断区、`测试数据/_make_s4_3_cases.py`（自测集构造脚本）

## 1. 目标

1. 错题录入后**异步诊断**，产出方案 §6.3 五维中的四维并落 `mistake_analyses`：
   - ① 知识点定位（`kp_ids`：题目已挂载的知识点，不再重复对齐）
   - ② 错因分类（主因 `cause_type` + 至多 2 个次因 `secondary_causes`）
   - ③ 第一处错误步骤（`error_step`，必须引用学生作答原文）
   - ⑤ 复习建议（`review_advice_md`：前置知识 + 关联笔记要点）
   - 正确解法（`explanation_md`：分步骤、LaTeX）
   - 另存 LLM 自评 `confidence`，供前端提示「把握较低」
2. 第四维「变式训练」**本卡不做**，`similar_questions_json` 保持 `null`（S4-4 负责生成 + 独立复算自检）。
3. 缺学生作答（或作答无法识别）时**只讲题不猜错因**：`cause_type="unknown"`、`secondary_causes=[]`、`error_step=NULL`，由代码强制而非依赖模型自觉。
4. 诊断能力落在 `ai/analyze/`，业务层只调适配器；严格 JSON + Pydantic 校验 + 最多 2 次重试，失败抛专用异常，不返回半解析结果。
5. 诊断与录入解耦：录入成功后 best-effort 入队（入队失败不影响录入），另提供手动重跑接口；已有诊断默认跳过，`force=true` 覆盖。
6. 前端详情页把 S4-2 的占位换成真实诊断区，支持「立即诊断 / 重新诊断」与任务轮询；列表的 `cause_type` 筛选从此有真实数据。

非目标：变式题生成与自检（S4-4）、知识图谱前置关系（S4-5，本卡的前置知识用 KP 树父节点近似）、掌握度回写（S4-7）、诊断结果的教师复核流、按错因出卷（S5）。

## 2. 范围

### 2.1 做

- `alembic/versions/0011_s4_3_mistake_analysis.py`：`mistake_analyses` 增 `secondary_causes`（`text[]`）与 `confidence`（`numeric(3,2)`），含 CHECK；可逆。
- `app/models/mistake_analysis.py`：同步两列 + 两个 CHECK。
- `app/ai/analyze/__init__.py`、`app/ai/analyze/mistake_analyzer.py`：`MistakeAnalysisResult` schema、Prompt 渲染、`analyze_mistake(...)` 单一入口、`MistakeAnalysisError`。
- `app/ai/prompts/mistake_analyze_v1.md`：错因诊断 Prompt（枚举约束、引用原文、缺作答只讲题、严格 JSON、不确定就说）。
- `app/services/mistake_analysis_service.py`：`enqueue_analysis`（自动/手动触发）与 `analyze`（任务内执行，含上下文构造、降级、upsert）。
- `app/tasks/analyze_mistake.py` + 注册：`mistake.analyze`（handler 不 commit）。
- `app/services/mistake_service.py`：`create_from_question` 在提交后调一次 `enqueue_analysis(force=False)`（best-effort）。
- `app/tasks/mistake_recognize.py`：handler 末尾调一次 `enqueue_analysis(force=False)`（best-effort，失败不影响识别成功）。
- `app/api/v1/mistakes.py`：新增 `POST /api/v1/mistakes/{mistake_id}/analyze`（202）。
- `app/schemas/mistake.py`：`MistakeAnalysisOut` 增 `secondary_causes` / `confidence` / `model` / `prompt_version`。
- 前端 `views/mistakes/MistakeDetailView.vue`：诊断区（主因徽标、次因 chips、置信度、第一处错误步骤、正确解法、复习建议）、空态「立即诊断」、右上「重新诊断」、任务轮询、低置信提示。
- 前端 `types/mistakes.ts` 同步 `MistakeAnalysis` 新字段。
- `测试数据/_make_s4_3_cases.py`：构造 ≥30 条「错题 + 学生作答」自测集（覆盖 6 类错因），供真机验收与准确率统计。
- 后端测试约 30 条 + 前端约 8 条（见 §10）。
- 文档：`API.md` §6 增 analyze 端点与 DTO 字段、`SCHEMA.md` §5.4 两列、`DECISIONS.md` D-046、`PROGRESS.md`、`AGENTS.md` §9.2/§9.6、实施计划勾选。

### 2.2 不做

- 不做变式题（`similar_questions_json` 恒为 `null`，S4-4 填）。
- 不重做知识点对齐：`kp_ids` 直接取 `question_kps` 已挂载的节点（S4-1 已完成对齐与打分），本卡只把它们喂给 Prompt 与写进诊断行。
- 不做知识图谱前置关系（`knowledge_edges` 目前 0 条）；「前置知识」用 KP 树**父节点名称**近似，图谱上线后可在 S4-6 增强，不改本卡落库结构。
- 不做诊断结果的教师/家长复核、不做人工纠错回写（论文里记为人工抽查）。
- 不做流式诊断（一次调用产出完整 JSON）、不做多轮追问。
- 不做错因统计新接口（S4-2 的 `stats.by_cause` 直接生效）。
- 不做「按错因生成复习计划」（S5-5）。
- 不为诊断引入本地模型或新依赖。

## 3. 设计决策

| # | 决策 | 理由 |
|---|---|---|
| D-1 | 诊断与录入**解耦**：录入成功后 best-effort 入队 `mistake.analyze`（入队失败只 `logger.warning`，不回滚录入），并暴露 `POST /mistakes/{id}/analyze` 手动重跑 | 诊断是 LLM 调用，可能失败/排队；录入是学生动作，不能因为诊断队列不可用而失败。S3-1「创建笔记后 best-effort 入队索引」已是同款口径 |
| D-2 | 自动触发时**已有诊断则跳过**（`force=False`）；手动接口默认 `force=true` | 避免同一错题被反复诊断烧钱；「重新诊断」是用户显式意图，默认就该覆盖 |
| D-3 | 诊断行 1:1（`uq_mistake_analyses_mistake_id`），重跑走 **UPDATE 覆盖**，不新增行；`created_at` 语义定为「最近一次诊断落库时间」，重跑时刷新 | 表结构已定 1:1；一个错题同一时刻只应有一份诊断，历史版本没有查询需求。用既有列表达「最近诊断」，不新增 `analyzed_at` 以免多一列无人用 |
| D-4 | 缺作答的 `unknown` 规则**由代码强制**：`my_answer_md` 为空 → 强制 `cause_type="unknown"`、`secondary_causes=[]`、`error_step=None`，模型输出被覆盖 | 方案 6.3 的硬要求「缺作答只讲题不猜错因」；LLM 有可能仍然编一个错因，代码兜底才能保证口径，也让前端可以据此隐藏「错因」区 |
| D-5 | 次因规范化：至多 2 个、去重、剔除与主因相同、剔除 `unknown`；主因为 `unknown` 时次因恒为空 | 次因用于统计与展示，混杂会让「概念不清 3 个」这种脏数据进入 S4-8 看板 |
| D-6 | 输入上下文固定六块：题干（截断 2000 字）、选项、题目标准答案、学生作答、题目已挂 KP 名称（≤3）、KP 父节点名称（≤5）、笔记检索片段 top-3（每条截断 200 字，带标题） | 诊断质量取决于「学生写了什么」+「这题考什么」+「学生自己的笔记怎么讲」；把上下文写死便于测试与论文描述 |
| D-7 | 笔记检索失败（embedding 超时/向量库异常）只记 WARNING 并**降级为空**，诊断照常跑 | 诊断的主证据是题目与学生作答；笔记只是提升「复习建议」的具体性，不能因为检索不可用就整条失败 |
| D-8 | `kp_ids` 取 `question_kps` 已挂载的节点（`weight` 降序，最多 3 个），本卡**不重新对齐** | S4-1 已完成「向量召回 top-10 + LLM 候选内选择」，重复对齐既慢又会与题库展示不一致；错题的知识点应等于题目的知识点 |
| D-9 | 诊断任务 handler 沿用 S2-7 约定：`(Session, payload) -> dict`，**不 commit**，由 runner 提交/回滚；`payload` 只带 `mistake_id` / `user_id`，不带题面正文 | 与 `question.extract`、`mistake.recognize` 一致；payload 落 `async_tasks` 表，不能塞学生作答正文（隐私 + 体积） |
| D-10 | upsert 后显式 `session.flush()` | S4-2 C1 的教训：`autoflush=False` 下不 flush，约束错误会逃出 handler 的 try 区间，任务卡在 `running`；flush 让失败在 handler 内暴露，交给 runner 重试 |
| D-11 | `enqueue_analysis` 走 `task_service.create_task`，任务名常量 `TASK_ANALYZE_MISTAKE = "mistake.analyze"` 定义在 service 内 | S3-1 已确认「task 反向导入 service 常量」避免循环导入 |
| D-12 | Prompt 与模型走**文件型 Prompt**（`ai/prompts/mistake_analyze_v1.md`）+ `get_llm_client()`，`scene="mistake"` | S3-4 约定只有 QA 读 `prompt_templates` 表；OCR 与切题都用文件 Prompt。`scene` 必须是 `llm_call_logs` 白名单内的值（S4-2 C1 踩过） |
| D-13 | 输出校验：`cause_type` 必须在 7 个枚举值内、`secondary_causes` ≤2、`error_step` 必须包含学生作答的**片段**（否则置 `None`）、`confidence` 0–1 | 「第一处错误步骤」是本卡最有说服力的输出，如果模型只是泛泛而谈「计算错误」，那这个字段就没有价值，宁可置空 |
| D-14 | 重试只针对 `ValidationError` / JSON 解析失败 / 传输错误，最多 2 次；仍失败抛 `MistakeAnalysisError`（任务 `failed`），旧诊断**保留不删** | 覆盖式更新不能「写一半」：失败就整体回滚，用户看到的是上一次有效诊断，而不是空白 |
| D-15 | 验收用**自测集**：S4-1 自编题 + 构造 ≥30 条学生作答（覆盖 6 类），由我逐条人工核对，报告写「自测集，非真实学生数据」并给出主因准确率 | 任务卡要求「30 道真实错题」；本项目没有真实学生数据，按 §6 只能标注为自测集，绝不能把构造数据冒充真实数据 |
| D-16 | 准确率口径：**主因命中率** = 主因与人工标注一致的条数 / 总条数（目标 ≥70%）；另记「主因或次因命中」与混淆矩阵 | 论文 6.5 要「错因判定准确率」，必须先把口径写死，避免事后挑数字 |

## 4. 数据模型（迁移 `0011_s4_3_mistake_analysis.py`）

### 4.1 `mistake_analyses` 增量（对应 `SCHEMA.md` §5.4）

| 列 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `secondary_causes` | `text[]` | 是 | — | 次因，至多 2 个；元素属于 `CAUSE_TYPES` |
| `confidence` | `numeric(3,2)` | 是 | — | LLM 自评置信度 0.00–1.00 |

新增约束：

- `ck_mistake_analyses_secondary_causes`：`secondary_causes IS NULL OR secondary_causes <@ ARRAY[六类 + 'unknown']::text[]`
- `ck_mistake_analyses_confidence`：`confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`

不变：`uq_mistake_analyses_mistake_id`（1:1）、`ck_mistake_analyses_cause_type`、`ix_mistake_analyses_kp_ids`（GIN）、`fk_mistake_analyses_mistake_id`（CASCADE）、`model` / `prompt_version` / `created_at` 均非空。

迁移要求：`down_revision = "0010_s4_2"`，`downgrade()` 先删两个 CHECK 再删两列；`alembic check` 不允许漂移。

### 4.2 枚举

无新增枚举。复用 `CauseType`（概念不清/计算失误/审题偏差/方法不当/知识遗忘/时间不足/unknown）。`mistake_analyses.cause_type` 与 `secondary_causes` 共用同一值集。

## 5. AI 层（`ai/analyze/`）

### 5.1 输入上下文（`mistake_analyzer.py` 的 `DiagnosisContext`）

| 字段 | 来源 | 截断 |
|---|---|---|
| `stem_md` | `questions.stem_md` | 2000 字 |
| `options` | `questions.options` | 全部（≤6 项） |
| `correct_answer_md` | `mistakes.correct_answer_md`，为空回退 `questions.answer_md` | 800 字 |
| `my_answer_md` | `mistakes.my_answer_md` | 1500 字 |
| `kp_names` | `question_kps` join `knowledge_points`，`weight` 降序，≤3 | — |
| `prerequisite_names` | 上述 KP 的父节点名称（`level >= 2` 才有），≤5 | — |
| `notes` | `retrieval_service.search_chunks(query=题干前 200 字, top_k=3)` 的 `hits`，每条 `note_title` + `snippet` | 每条 200 字 |

**没有笔记命中**时该块为空，Prompt 里明确「没有找到学生的相关笔记，不要编造笔记内容」。

### 5.2 输出 schema

```python
class MistakeAnalysisResult(BaseModel):
    cause_type: CauseType
    secondary_causes: list[CauseType] = Field(default_factory=list, max_length=2)
    error_step: str | None = None
    explanation_md: str = Field(min_length=20)
    review_advice_md: str = Field(min_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
```

`model_validator` 负责 D-5 的规范化（去重、剔除主因与 `unknown`、超 2 截断）。

### 5.3 Prompt 要点（`ai/prompts/mistake_analyze_v1.md`）

1. 角色：高中数学老师，给一名学生讲错题。
2. 错因只能从 6 类中选 1 个主因 + 至多 2 个次因，**必须给出选择依据**（写进 `explanation_md` 首段）。
3. `error_step` 必须引用学生作答原文（"你写的是……，第 k 步应为……"）；找不到明确错误就返回 `null`，不要硬凑。
4. `explanation_md` 分步骤、公式用 LaTeX（`$...$`），先讲本题再点易错处。
5. `review_advice_md` 给 2–3 条可执行建议，优先引用给定的知识点与笔记片段；没有笔记片段时只讲知识点。
6. 学生作答缺失时：`cause_type` 填 `"unknown"`、`error_step` 为 `null`，只讲题不猜错因。
7. 严格输出 JSON，不要 Markdown 代码围栏以外的解释。
8. 不确定时降低 `confidence`，并在 `review_advice_md` 里说明需要人工确认的点。

### 5.4 调用与错误

```python
def analyze_mistake(
    context: DiagnosisContext, *, llm_client: LLMClient | None = None, max_retries: int = 2
) -> MistakeAnalysisResult: ...
```

- `client.chat(messages, temperature=0.2, max_tokens=2000, scene="mistake")`；`temperature` 用 0.2 而不是 0：错因判断需要一点语义弹性，但必须可复现（同一输入多次调用结论应稳定，验收时抽 3 条各跑 2 次核对一致性）。
- 解析用既有 `loads_json_object`（S4-2 已用于视觉）；只捕 `ValidationError` / `ValueError` / 传输异常。
- 全部重试失败 → `MistakeAnalysisError(f"诊断失败（已尝试 {n} 次）：{last_error}")`。
- 缺作答时在**代码层**覆盖模型输出（D-4），并记 `logger.info("mistake_analyze_unknown_answer", extra=...)`。

## 6. 服务层（`services/mistake_analysis_service.py`）

### 6.1 `enqueue_analysis`

```python
TASK_ANALYZE_MISTAKE = "mistake.analyze"

def enqueue_analysis(
    session: Session,
    *,
    owner: User,
    mistake_id: int,
    queue: TaskQueue,
    force: bool = False,
    skip_if_analyzed: bool = True,
) -> AsyncTask | None:
```

- `skip_if_analyzed=True` 且已有诊断 → **不建任务**，返回 `None`（自动触发路径用，避免为一条已诊断的错题白建一行 `async_tasks`）。
- `skip_if_analyzed=False`（手动接口用）→ 一定建任务，`force` 放进 payload 由 handler 决定是否真的重跑；这样接口恒定返回 202，前端只有一套轮询代码。
- 入队走 `task_service.create_task(session, owner=owner, name=TASK_ANALYZE_MISTAKE, payload={"user_id", "mistake_id", "force"}, queue=queue)`；它自己落 `async_tasks` 行并提交。
- **入队失败不致命**：调用方捕获异常 → WARNING，录入/识别结果照常返回。

**两个触发点**（语义不同，都在业务完成后）：

1. **题库录入**：`create_from_question` 在 `_commit(session)` 之后调用 `enqueue_analysis(force=False)`。此时错题已提交，入队只影响后续诊断。
2. **拍照录入**：放在 `tasks/mistake_recognize.py` 的 handler **末尾**（`task_create_mistake` 返回错题、`result` 组装完之后）。原因：只有 handler 手里同时有 `mistake_id` 与 `owner`；`task_service.create_task` 会提交当前 session，沿途的 `mistake` / `question` / `question_kps` 行会**提前提交**——这在本 handler 里是可接受的（它紧接着就 `return`，没有后续可能失败的写操作），且 runner 之后那次提交是幂等的。若入队抛错，handler 捕获并记 WARNING，`result` 里带 `analysis_enqueued=false`，识别任务仍然 `succeeded`。

### 6.2 `analyze`（任务内执行）

```python
def analyze(session: Session, *, user_id: int, mistake_id: int) -> tuple[MistakeAnalysis, dict]
```

步骤（一个事务，由 runner 提交）：

1. 取错题：`select(Mistake).where(Mistake.id == mistake_id, Mistake.user_id == user_id)`；查不到 → `NotFoundError("错题不存在")`（他人与不存在同为 404，D-7 口径一致）。
2. 取题目 `questions`（不存在视为数据损坏 → `NotFoundError("题目不存在")`）。
3. 取 `kp_ids` + `kp_names`：`question_kps` join `knowledge_points`，`weight` 降序 ≤3。
4. 取前置名称：上述 KP 的父节点（`knowledge_points.parent_id`，同 subject），≤5。
5. 取笔记片段：`retrieval_service.search_chunks(session, user_id=user_id, query=stem_md[:200], top_k=3)`；**整段 try/except**：任何异常 → `notes=[]` + WARNING `mistake_analyze_retrieval_failed`。
6. 组装 `DiagnosisContext` → `analyze_mistake(context)`。
7. upsert：查 `MistakeAnalysis.mistake_id == mistake_id`；存在则原地改字段并 `created_at = now()`，不存在则 `session.add(...)`；`kp_ids` 用步骤 3 的结果；`model` 取 `settings.llm_model`、`prompt_version` 取 `mistake_analyze_v1`。
8. `session.flush()`（D-10）。
9. 返回 `(analysis, {"mistake_id":..., "cause_type":..., "secondary_causes": [...], "confidence":..., "retrieval_hits": n})`，供任务 `result` 展示。

**不做**：不写 `mistakes.status`、不动 `correct_streak`（S4-7 掌握度才回写）、不生成变式题。

### 6.3 `has_analysis`

```python
def has_analysis(session: Session, mistake_id: int) -> bool: ...
```

一行 `select(MistakeAnalysis.id).where(MistakeAnalysis.mistake_id == mistake_id).limit(1)`，供任务 handler 在 `force=false` 时短路，避免白白花一次 LLM 调用。

### 6.4 越权与错误

- 他人错题、不存在错题：`NotFoundError`（404/40400）。
- LLM 失败：`MistakeAnalysisError` → handler 抛出让 runner 置 `failed`（重试 3 次、2s/4s 退避由 runner 决定）；**旧诊断保留**（D-14）。
- 数据库约束失败（如次因越界）：让异常冒泡到 runner，不吞。

## 7. 异步任务（`tasks/analyze_mistake.py`）

```python
@register(TASK_ANALYZE_MISTAKE)
def run_analyze_mistake(session: Session, payload: dict) -> dict:
    user_id = int(payload["user_id"])
    mistake_id = int(payload["mistake_id"])
    if not payload.get("force", True) and mistake_analysis_service.has_analysis(session, mistake_id):
        # force=false 且已有诊断：不重复花 LLM 调用，直接回 skipped 让前端收尾
        return {"mistake_id": mistake_id, "skipped": True}
    _analysis, summary = mistake_analysis_service.analyze(
        session, user_id=user_id, mistake_id=mistake_id
    )
    return summary
```

- `payload` 为 `{"user_id", "mistake_id", "force"}`（D-9），不含题面正文。
- handler **不 commit**；`session.flush()` 在 service 内完成。
- 任务结果 `result`（`status=succeeded` 后）：

```json
{"mistake_id": 12, "cause_type": "概念不清", "secondary_causes": ["计算失误"], "confidence": 0.82, "retrieval_hits": 2}
```

跳过时：`{"mistake_id": 12, "skipped": true}`。

## 8. 接口

### 8.1 `POST /api/v1/mistakes/{mistake_id}/analyze`

- 权限：登录用户，仅本人（他人 → 404/40400）
- 类型：异步（202 + `GET /api/v1/tasks/{task_id}` 轮询）
- 入参：query `force`（bool，默认 `true`）
- 行为：`enqueue_analysis(session, owner=current_user, mistake_id=..., force=force, skip_if_analyzed=False, queue=...)` → 恒定建任务并返回 202。`force=false` 且已有诊断时，任务立即以 `succeeded` 结束、`result={"mistake_id": 12, "skipped": true}`（前端据此提示「已有诊断」，而不是空转或报错）。

  > 说明：`skipped` 走任务而不是 409，是为了让前端只有一套轮询代码；代价是多一条 `async_tasks` 行。
- 成功：**202** `Envelope[TaskOut]`
- 错误：`404/40400` 错题不存在或无权访问；`422/42200` `force` 非布尔；`500/50000`「任务队列不可用」；`401/40100`

### 8.2 `GET /api/v1/mistakes/{mistake_id}` 的 `analysis` 扩展

```json
"analysis": {
  "cause_type": "概念不清",
  "secondary_causes": ["计算失误"],
  "error_step": "你写的是「对称轴 x=1」，应为 x=2",
  "explanation_md": "……",
  "review_advice_md": "……",
  "kp_ids": [133, 116],
  "confidence": 0.82,
  "model": "qwen-plus",
  "prompt_version": "mistake_analyze_v1",
  "created_at": "2026-11-03T11:20:31.004Z"
}
```

- `analysis=null` 表示尚未诊断（或诊断失败且从未成功过）。
- `cause_type="unknown"` 表示学生作答缺失，前端展示为「未提供作答，仅讲题」。

### 8.3 与既有接口的关系

- 列表 `GET /mistakes?cause_type=...` 不需要改动（S4-2 已用 `EXISTS` 过滤 `mistake_analyses.cause_type`）。
- `GET /mistakes/stats` 的 `by_cause` 从此有数据（S4-2 已实现聚合）。
- 列表的 `cause_type` 字段来自 `mistake_analyses.cause_type`（S4-2 已实现批量补字段），本卡只填数据。

## 9. 前端（`views/mistakes/MistakeDetailView.vue`）

### 9.1 诊断区

| 状态 | 展示 |
|---|---|
| `analysis === null` | 占位文案「尚未诊断」+ 按钮「立即诊断」 |
| `cause_type === "unknown"` | 徽标「错因未知（未提供作答）」+ 只展示正确解法与复习建议，隐藏「第一处错误步骤」 |
| 正常诊断 | 主因徽标（6 类中文 + 颜色）、次因 chips、置信度条（`confidence`，`< 0.5` 时显示「诊断把握较低，建议人工确认」）、「第一处错误步骤」（纯文本，等宽引用块）、「正确解法」（`MdPreview`）、「复习建议」（`MdPreview`） |
| 诊断中 | 诊断区显示「诊断中…」+ 已等待秒数，禁用「重新诊断」 |

### 9.2 交互

- 「立即诊断 / 重新诊断」→ `POST /mistakes/{id}/analyze`（`force=true`）→ 202 拿 `task_id` → 4s 轮询 `getTask` → 终态后 `getMistake` 刷新诊断区；失败展示 `task.error` + 可重试。
- 组件卸载时清定时器（沿用 S4-2 `MistakeNewView` 的 `disposed` 模式）；迟到的轮询结果不得覆盖新状态。
- `POST /analyze` 后不重置「我的作答」草稿（与 S4-2 评审 M8 的教训一致：先把草稿保住）。

### 9.3 类型与 API 封装

- `types/mistakes.ts`：`MistakeAnalysis` 增 `secondaryCauses: MistakeCauseType[]`、`confidence: number | null`、`model: string`、`promptVersion: string`。
- `api/mistakes.ts`：新增 `analyzeMistake(id: number, force = true): Promise<TaskOut>`（GET 用 `compactQuery`，POST 无体只带 query）。
- 组件里禁止直接 import axios（§9.5）。

## 10. 测试计划

### 10.1 后端（约 30 条）

| 文件 | 覆盖 |
|---|---|
| `tests/test_mistake_analyzer.py`（约 10） | JSON 解析成功；`cause_type` 非法 → 重试后抛 `MistakeAnalysisError`；`secondary_causes` 超 2 截断、去重、剔主因；缺作答强制 `unknown`（模型返回 `概念不清` 也被覆盖）；`error_step` 不含作答片段 → 置 `None`；`confidence` 越界校验；传输异常重试计数；Prompt 渲染变量缺失抛错 |
| `tests/test_mistake_analysis_service.py`（约 12） | `analyze` 正常 upsert（INSERT）；重跑 UPDATE 同一行且 `created_at` 刷新；越权/不存在 404；检索异常降级为空且诊断仍成功；`kp_names` 取 `question_kps` 权重排序；无父节点时前置为空；缺作答走 unknown；`flush` 被调用；`enqueue_analysis` 已有诊断且 `force=False` 跳过；`force=True` 入队；入队失败返回 None 不抛 |
| `tests/test_mistake_analysis_task.py`（约 4） | handler 返回 dict 且不 commit；`payload` 只用 `mistake_id/user_id`；LLM 失败向上抛（runner 重试语义）；成功时 `result` 字段齐全 |
| `tests/test_mistakes_api.py`（+4） | `POST /analyze` 202 + 任务名正确；他人错题 404；`force=false` 已有诊断 → 任务 succeeded `skipped=true`；详情 DTO 含新字段 |

### 10.2 前端（约 8 条）

- 空态显示「立即诊断」，点击后调用 `analyzeMistake(12, true)` 并开始轮询；
- 轮询 `succeeded` 后重新 `getMistake` 并渲染主因/次因/置信度；
- `cause_type="unknown"` 时不渲染「第一处错误步骤」，显示「未提供作答」；
- `confidence < 0.5` 显示「把握较低」提示；
- 轮询失败展示错误与重试；
- 卸载后迟到轮询不导航、不弹提示（沿用 S4-2 的 fake-timers 写法）；
- 诊断中「重新诊断」按钮禁用；
- 诊断刷新不重置作答草稿。

## 11. 验收

### 11.1 自动

- `cd backend; ..\.venv\Scripts\python.exe -m pytest -q` 全绿（后端基线 **956**，预期 ≥ 980）；
- `cd web; npm run test:run -- --pool=threads` 全绿（前端基线 **180**，预期 ≥ 188）；
- `npm run build` 通过；`alembic check` 无漂移、`alembic heads` 单头 `0011_s4_3`。

### 11.2 真机（必须贴实测输出）

1. 起服务（Redis db 6、`uvicorn :8031`、ARQ worker）。
2. 跑 `测试数据/_make_s4_3_cases.py`：基于 S4-1 自编题构造 **≥30 条**「错题 + 学生作答」，覆盖 6 类错因，每条带人工标注的期望 `cause_type`。
3. 逐条触发诊断（自动入队或 `POST /analyze`），记录每条：`cause_type` / `secondary_causes` / `confidence` / `error_step` 是否引用作答 / 耗时。
4. 人工逐条核对，输出：
   - **主因准确率** = 命中 / 总数（目标 ≥70%）；
   - 主因或次因命中率；
   - 混淆矩阵（行=人工标注，列=模型输出）；
   - 抽 3 条重复跑 2 次的一致性结果。
5. 边界：无作答错题 → `unknown` 且 `error_step=null`；无笔记用户 → 复习建议不含笔记引用；诊断失败（构造非法 LLM 返回）→ 任务 `failed` 且旧诊断保留。
6. 文档与 PROGRESS 写「自测集，非真实学生数据」。

### 11.3 如实记录的边界（预判）

- 错因由 LLM 判断，与人工标注的分歧主要在「概念不清 vs 方法不当」「计算失误 vs 审题偏差」；
- 自测集的作答是人工构造的，可能比真实作答更「典型」，准确率不能直接外推到真实学生；
- 前置知识用 KP 父节点近似，不等价于真实前置关系（S4-5 才建）；
- 笔记检索对「复习建议」的具体性影响未做 A/B。

## 12. 文档同步

- `docs/API.md` §6：新增 `POST /mistakes/{id}/analyze`（202、`force`、`skipped`）、`analysis` 新字段、错误码。
- `docs/SCHEMA.md` §5.4：两列 + 两个 CHECK；§10 枚举不变。
- `docs/DECISIONS.md`：`D-046 错因诊断（S4-3）`（诊断与录入解耦、unknown 代码强制、1:1 覆盖、检索可降级、自测集口径）。
- `docs/PROGRESS.md`：S4-3 条目、测试计数、验收准确率表、遗留。
- `AGENTS.md` §9.2 增「错因诊断（S4-3）」一段；§9.6 增锚点（analyzer / service / task / prompt）。
- `docs/AI协作开发实施计划.md`：S4-3 勾选 + 实施记录。
- 若新增环境变量（预计无）→ `.env.example`；新增依赖（预计无）→ `requirements.txt`。

## 13. 已知限制（实现后按实回填）

- 预判：错因分类在「概念不清 / 方法不当」上边界模糊；`error_step` 依赖学生作答足够具体，只写「算错了」时多半为 `null`；笔记检索 top-3 可能召回不相关片段（S3-2 的 rerank 可开但会增加耗时）；诊断耗时约 5–15s（真机回填）；`confidence` 未校准，只能当提示。

## 14. 开工前必须先验证的技术假设

1. `numeric(3,2)` 的 CHECK 与 SQLAlchemy `Numeric` 映射在本项目 PG 16 上正常（写入 0.82、读取为 `Decimal`）。
2. `text[]` 的 `<@` CHECK 可用（`secondary_causes <@ ARRAY[...]::text[]`）。
3. `qwen-plus` 对 6 类错因的稳定性：同一题跑 2 次结论一致率（抽 3 条验证）。
4. `retrieval_service.search_chunks` 在 ARQ worker 进程内可调用（embedding 客户端、pgvector 均在 worker 可用）。
5. `scene="mistake"` 已能落 `llm_call_logs`（S4-2 C1 已修，直接复用）。
