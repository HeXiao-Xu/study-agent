# S6-1 Agent 工具集（11 个工具 + schema 导出）（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S6-1。产出 `backend/app/ai/agents/tools/*.py`。
> 方案依据：`docs/个性化学习智能体-毕业设计完整方案.md` §6.7「工具清单」。
> 状态：**已确认**（2026-11-17）。实现按 `docs/plan/s6-1-agent-tools.md` 执行。
> 范围：只做工具层与工具单测、schema 导出、独立 CLI 验证；**不做** LangGraph 状态机、`agent_tasks/agent_steps` 表、Agent API（S6-2），不做任务 A/B 编排（S6-3/S6-4）。

## 1. 目标与非目标

### 1.1 目标

1. 在 `backend/app/ai/agents/tools/` 实现方案 §6.7 的 **11 个工具**（任务卡写「10 个」，以更细的方案表为准，见 §2 D1）。
2. 每个工具都有 Pydantic 入参/出参模型，入参 `extra="forbid"`；工具描述写清「什么时候用、参数含义、返回什么」。
3. 提供统一注册表与调用入口：按工具名 + 已校验入参调用，返回 Pydantic 出参；供 S6-2 的 LangGraph `act` 节点直接使用。
4. 提供 OpenAI function-calling 兼容的 JSON schema 导出：`backend/data/agent_tools.json`，由脚本可重复生成。
5. 提供独立 CLI：列出工具、导出 schema、用真实库按工具名调用（验收「11 个工具都能独立跑通」）。
6. 每个工具单独单测；外部 LLM 调用全部 mock；不新增依赖、不新增表、不改 API。
7. 工具层只复用现有 service / ai 适配器，不复制业务公式；确实缺口的 service 只做**向后兼容的增量**（§6）。

### 1.2 非目标（留给后续卡）

- 不做 `graph.py`、State、plan/act/observe/reflect/confirm 路由、最大步数 12、token 预算、`agent_steps` 持久化（S6-2）。
- 不做任务 A（周笔记整理 + 思维导图）与任务 B（错题组卷 + 人工确认）编排（S6-3/S6-4）。
- 不做前端任务进度页（S6-5）、失败场景加固与重跑幂等（S6-6）。
- 不做工具级 HTTP 接口；`API.md §10` 仍是 S6-2 的三条占位接口。
- 不做「工具直写库」：`generate_questions` 只返回题目草稿、`create_review_plan` 只返回计划建议，持久化与人工确认由 S6-2/S6-4 负责（D2）。
- 不新增 `llm_call_logs.scene`：`generate_questions` 复用既有 `gen` 场景，不为此加迁移。
- 不改 S5-1 组卷内核、S5-4 判分、S5-5 复习刷新、S5-3 PDF 渲染的既有口径。

## 2. 用户已确认的决策（2026-11-17）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 工具数量与清单 | 按方案 §6.7 的 **11 个**（含 `calculator`）；任务卡「10 个」视为旧计数，spec/文档注明 |
| D2 | 写操作口径 | 工具**只产出草稿/建议，不写库**；真正落库与人工确认留给 S6-2 的 human-in-the-loop |
| D3 | 工具层定位 | 业务函数 + 注入 `ToolContext`；「纯函数」落实为**无隐藏全局状态、相同输入相同输出**，DB/LLM 依赖显式注入并在测试中 mock |
| D4 | 数据来源 | 全部复用现有 service / ai 适配器；不改 SQL 检索入口、不重复实现掌握度公式 |
| D5 | schema 导出格式 | OpenAI function-calling `{"type":"function","function":{name,description,parameters}}`，按固定顺序输出，文件可重复生成且进仓库 |
| D6 | 验收方式 | `pytest` 全绿 + 11 个工具各自单测 + CLI 真实库逐个调用（`search_notes`/`generate_questions` 允许真实外部调用，其余本地） |

## 3. 架构与目录

```
backend/app/ai/agents/tools/
├── __init__.py            # 导出 TOOLS / invoke_tool / build_openai_tools / ToolContext
├── base.py                # ToolContext、ToolSpec、ToolError、输入/输出基类
├── registry.py            # 11 个 ToolSpec 的登记与顺序
├── search_notes.py
├── list_notes.py
├── get_kp_subgraph.py
├── list_mistakes.py
├── get_mastery.py
├── search_questions.py
├── generate_questions.py  # LLM 适配器 + 工具入口（Prompt 在 ai/prompts/）
├── make_mindmap.py        # 纯函数
├── create_review_plan.py  # 纯规划，不写库
├── export_paper_pdf.py
├── calculator.py          # 纯函数
└── schema_export.py       # JSON schema 组装（供脚本/测试共用）

backend/app/ai/prompts/agent_gen_questions_v1.md   # generate_questions 的 Prompt
backend/data/agent_tools.json                      # 导出的 schema（进仓库）
scripts/export_agent_tools.py                      # 生成 schema 文件
scripts/agent_tools.py                             # list / schema / call CLI
backend/tests/test_agent_tool_*.py                 # 每个工具一个测试文件 + 注册表/schema/服务增量
docs/AGENT_TOOLS.md                                # 工具目录、入参出参、调用示例
```

分层约束：

- 工具属于 `ai/` 层，可以 import `app.ai.*` 与 `app.services.*`；**不得**被 `app/services` 反向依赖。
- 工具不得自行 `commit`/`rollback`；只读查询，不产生写事务。
- 路由/Agent 图只通过 `registry.invoke_tool()` 调工具，不直接 import 各工具模块。

## 4. 公共契约

### 4.1 `ToolContext`

```python
@dataclass(frozen=True)
class ToolContext:
    session: Session          # 只读查询用；工具不得 commit
    user: User                # 当前学生（含 id / role），由调用方回表取
    now: datetime             # UTC；注入以便测试固定时间
```

`now` 由 `default_factory=lambda: datetime.now(timezone.utc)` 提供；调用方可覆盖。

### 4.2 输入/输出基类与错误

- `ToolInput(BaseModel)`：`model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`。
- `ToolOutput(BaseModel)`：`model_config = ConfigDict(extra="forbid")`。
- 错误：
  - `ToolInputError(InvalidParamError)`：入参 Pydantic 校验失败或业务前置校验失败（422/42200）。
  - `NotFoundError` / `ForbiddenError` 等既有 `AppError`：由 service 直接抛出，工具不包装。
  - `ToolExecutionError(AppError, code=50000)`：工具执行中的意外异常或 LLM 重试耗尽；对外固定中文话术，不泄露 Prompt/模型响应/堆栈，内部 `logger.exception` 带 `trace_id`。
- `invoke_tool(name, ctx, payload)`：
  1) 按名字取 `ToolSpec`，不存在 → `NotFoundError("工具不存在")`；
  2) `input_model.model_validate(payload)`，失败 → `ToolInputError("工具参数不合法：<第一条中文可读信息>")`（不拼字段路径/英文类型名优先，保持简短）；
  3) 调 `handler(ctx, input)`，返回 `output`；
  4) 意外异常统一 `ToolExecutionError`，不吞日志。

### 4.3 `ToolSpec` 与导出的 schema

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                 # 与方案 6.7 完全一致
    description: str          # 中文，写清何时用/参数/返回
    input_model: type[ToolInput]
    output_model: type[ToolOutput]
    handler: Callable[[ToolContext, Any], ToolOutput]
    write: bool = False       # S6-1 全为 False
```

- `build_openai_tools()`：按 `registry.TOOL_ORDER` 顺序返回 11 条 OpenAI function 定义；`parameters` = `input_model.model_json_schema()`。
- `build_export_payload()`：

```json
{
  "version": 1,
  "tools": [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}],
  "outputs": {"<tool_name>": {"type": "object", ...}}
}
```

- `backend/data/agent_tools.json` 由 `scripts/export_agent_tools.py` 写入；测试断言仓库文件与现场生成结果完全一致（防漂移）。不含时间戳，保证可复现。

### 4.4 通用口径

- 时间：入参日期为 `datetime.date`（ISO）；窗口统一 UTC；`list_notes`/`list_mistakes` 的 `end_date` 含当天（内部转 `end_date+1 天 00:00 UTC - 1µs`）。
- 数量上限：所有 `limit`/`count`/`top_k` 都有上限（见各工具），超限 422，不静默截断。
- 文本上限：工具回给 LLM 的正文统一截断并带 `truncated` 标记，防止单条工具输出挤爆 token 预算。
- 排序：所有列表输出顺序确定（时间倒序 + id 倒序，或 kp_id 升序），保证同输入同输出、步骤可回放。
- 权限：工具只查 `ctx.user.id` 的数据；题库是公共语料（与 S4-1 一致），但错题/笔记/掌握度/试卷严格按本人过滤。

## 5. 工具逐个定义

> 以下 `input`/`output` 是字段清单（Pydantic 模型另加 `title` 等 schema 元数据）；未标注默认值即必填。

### 5.1 `search_notes`

- 用途：在学生个人知识库里做混合检索，返回可引用的片段；需要「笔记里怎么说的」时用。
- input：
  - `query: str`（1–500）
  - `subject_id: int | None`（≥1）
  - `folder: str | None`（≤200）
  - `start_date: date | None` / `end_date: date | None`（含当天；`end < start` → 422）
  - `chunk_types: list[Literal["note","question","formula"]] | None`（去重、非空）
  - `top_k: int = 8`（1–20）
  - `retrieval: Literal["vector","hybrid","hybrid_rerank"] = "hybrid"`
- output：`query`、`retrieval`、`top_k`、`hit_count`、`elapsed_ms`、`embedding_ms`、`hits[]`
  - 每 hit：`chunk_id`、`note_id`、`note_title`、`chunk_index`、`chunk_type`、`heading_path`、`page_no`、`content`（截 1200 字）、`snippet`、`truncated`、`rrf_score`、`rerank_score`
- 行为：调 `retrieval_service.search_chunks(session, user_id=ctx.user.id, query=..., top_k=..., retrieval=..., scope=RetrievalScopeIn(...), debug=False)`；只保留所需字段，不返回 debug 块。
- 错误：空 query/非法 top_k → 422（service 抛 `InvalidParamError`）；外部 Embedding/Rerank 失败按 service 现有异常向上抛。

### 5.2 `list_notes`

- 用途：按时间范围/标签/学科列本人笔记的**元数据**（不返回正文）；「上周写了哪些笔记」时用。
- input：`start_date`、`end_date`（可空）、`tags: list[str]`（≤10，去空去重）、`subject_id`、`limit: int = 20`（1–50）。
- output：`total`、`items[]`：`note_id`、`title`、`subject_id`、`tags`、`folder`、`created_at`、`updated_at`。
- 行为：`note_service.list_notes(session, owner=ctx.user, params=PageParams(1, limit), sorting=SortParams("created_at","desc"), created_from=..., created_to=..., tag=..., subject_id=...)`；多标签时按第一个标签过滤（`notes.tags @> ARRAY[tag]`），其余标签在内存过滤，`total` 为服务端分页总数并在文档注明「多标签过滤后可能小于 total」。**不返回正文**，需要正文时用 `search_notes`。
- 错误：非法日期/limit → 422。

### 5.3 `get_kp_subgraph`

- 用途：取一个知识点及其 N 跳前置/相关/包含关系，供聚类、导图、薄弱点分析；**只返回已审核边**（`review_status=approved`）。
- input：`kp_id: int`（≥1）、`depth: int = 1`（1–3）。
- output：`center_kp_id`、`subject_id`、`node_count`、`edge_count`、`nodes[]`、`edges[]`
  - node：`kp_id`、`name`、`level`、`parent_id`、`exam_weight`、`mastery`（本人折算 `M_t`，未评估 `null`）
  - edge：`src_kp_id`、`dst_kp_id`、`relation`、`weight`
- 行为：
  1) `session.get(KnowledgePoint, kp_id)`，不存在 → `NotFoundError("知识点不存在")`；
  2) 调 `graph_service.snapshot(subject_id=..., user_id=ctx.user.id, now=ctx.now)`；
  3) 纯函数 `_bfs_subgraph(snapshot, center=kp_id, depth)`：把 approved 边视为**无向**，从中心按跳数 BFS（含中心），返回节点与两端都在结果内的边；节点/边按 id 升序输出。
- 说明：当前学科 108 个知识点，snapshot 一次取全学科可接受；不新增 SQL、不改图谱服务。单学科上千节点时再改成 SQL 层下推（记录为已知边界）。

### 5.4 `list_mistakes`

- 用途：按知识点/状态/时间筛本人错题；「最近错了哪些」「按薄弱知识点聚合」时用。
- input：`kp_ids: list[int] | None`（1–20，去重）、`status: Literal["待订正","已订正","已掌握"] | None`、`start_date`、`end_date`、`limit: int = 20`（1–50）。
- output：`total`、`items[]`：`mistake_id`、`question_id`、`status`、`correct_streak`、`stem_excerpt`、`subject_id`、`qtype`、`difficulty`、`kp_names`、`cause_type`、`created_at`、`last_review_at`。
- 行为：`mistake_service.list_mistakes(session, user_id=ctx.user.id, filters=MistakeFilters(kp_ids=..., status=..., created_from=..., created_to=...), page=PageParams(1, limit), sort=SortParams("created_at","desc"))`；结果映射为工具出参（不返回作答/答案正文）。
- 服务增量：`MistakeFilters` 增加 `kp_ids: list[int] | None`（与 `kp_id` 共存；多个 kp 用 OR 的 `EXISTS`，语义与现有 `kp_id` 一致：命中题目挂载或诊断结论任一）。

### 5.5 `get_mastery`

- 用途：批量取本人知识点掌握度 `M_t` 与到期时间；组卷/复习推荐前先看薄弱项。
- input：`kp_ids: list[int]`（1–50，去重）。
- output：`items[]`、`assessed_count`、`unassessed_kp_ids[]`、`missing_kp_ids[]`
  - item：`kp_id`、`kp_name`、`subject_id`、`exam_weight`、`mastery_t`（`float|null`）、`assessed`、`attempts`、`stability`、`last_practice_at`、`due_at`
- 行为：新增 `mastery_service.mastery_details(session, user_id=..., kp_ids=..., now=ctx.now)`：两条 `IN` 查询（知识点 + 掌握度），逐行用 `decayed_mastery` 算 `M_t`；无掌握度行的知识点 `assessed=false`、`mastery_t=null`（**不冒充 0**）。`missing_kp_ids` = 知识点表里不存在；`unassessed_kp_ids` = 存在但无掌握度行。
- 服务增量：`mastery_service.mastery_details()` 返回 `list[KpMasteryState]`（dataclass），供本工具与 `create_review_plan` 共用；不改既有 `list_mastery/mastery_values` 行为。

### 5.6 `search_questions`

- 用途：按知识点/题型/难度取题库题目**题干**（不返回答案），供组卷取材或生成变式前定位原题。
- input：`kp_ids: list[int] | None`（1–20）、`subject_id`、`qtype: Literal["单选","多选","填空","解答"] | None`、`difficulty: int | None`（1–5）、`exclude_recent_days: int = 14`（0–90，0=不排除）、`limit: int = 20`（1–50）。
- output：`total`、`items[]`：`question_id`、`stem_md`（截 2000 字，带 `truncated`）、`stem_excerpt`、`options`（`[{key,text}]|null`）、`qtype`、`difficulty`、`origin`、`verified`、`kp_names`；不返回 `answer_md/analysis_md`。
- 行为：调 `question_service.list_questions(..., filters=QuestionFilters(kp_ids=..., subject_id=..., qtype=..., difficulty=..., exclude_user_id=ctx.user.id, exclude_done_since=ctx.now - timedelta(days=exclude_recent_days)))`；`limit` 即 `page_size`；出参按「已验证优先、id 倒序」稳定排序（页内排序，`total` 仍为过滤后总数）。
- 服务增量：`QuestionFilters` 增加 `kp_ids`、`difficulty`、`exclude_user_id`、`exclude_done_since`；`build_questions_query` 增加对应条件。近期排除口径与 S5-1 一致：`mistakes` 中本人最近一次「做过」时间 = `greatest(last_review_at, created_at)`，晚于 `exclude_done_since` 的题排除；未传新字段时 SQL 与现状完全一致（现有调用不受影响）。

### 5.7 `generate_questions`

- 用途：题库不足时按知识点 + 难度生成新题**草稿**；只返回候选，不入库、不写日志正文。
- input：`kp_id: int`（≥1）、`difficulty: int = 3`（1–5）、`count: int = 3`（1–5）、`qtype: Literal["单选","多选","填空","解答"] = "解答"`。
- output：`kp_id`、`kp_name`、`difficulty`、`qtype`、`count`、`questions[]`、`prompt_version`、`attempts`
  - question：`stem_md`、`options`、`answer_md`、`analysis_md`、`qtype`、`difficulty`
- 行为：
  1) `session.get(KnowledgePoint, kp_id)` + 所属学科名（一次 `session.get(Subject, ...)`），不存在 → 404；
  2) 渲染 `ai/prompts/agent_gen_questions_v1.md`（Jinja2 `StrictUndefined`），把知识点名、学科、难度档位、题型、数量、返回 JSON 结构写进 Prompt；
  3) 调 `get_llm_client().chat(..., scene="gen", temperature=0.7, max_tokens=3500)`；复用 `ai/gen/json_repair.loads_lenient_json` 与 `variant_generator.GeneratedVariant` 做严格校验（题型↔选项交叉校验、长度限制）；
  4) 条数不符/JSON 非法/字段非法 → 重试，最多 2 次（共 3 次调用）；仍失败 → `ToolExecutionError("题目生成失败，请稍后重试")`；
  5) 返回草稿，**不写 `questions` 表**；`attempts` 为实际调用次数。
- 说明：复用 `gen` 场景（`llm_call_logs.scene` 现有值集），不新增迁移；`prompt_version="agent_gen_questions_v1"` 记在工具出参，S6-2 写步骤日志时一并落库。

### 5.8 `make_mindmap`

- 用途：把节点/边转成 Mermaid 思维导图文本，渲染失败时有纯文本降级。
- input：`title: str = "思维导图"`（1–100）、`nodes: list[{id: str|int, name: str, parent_id: str|int|None}]`（1–80，id 去重）、`edges: list[{src, dst, relation?}]`（≤160，可空）。
- output：`mermaid`、`fallback_text`、`node_count`、`edge_count`、`truncated`、`mode`（`mindmap|graph`）。
- 行为（纯函数，不触库）：
  - 优先用 `parent_id` 建树；缺 `parent_id` 时用 `edges`（`contains` 优先）建树；
  - 树合法（无环、每节点至多一个父）→ `mode="mindmap"`，`mindmap` 输出 `mindmap\n  root((标题))\n    ...`；
  - 有环/多父/无根 → `mode="graph"`，输出 `graph TD` + 带方括号标签的边（仍是可渲染 Mermaid）；
  - `fallback_text` 始终输出缩进树/边清单（Mermaid 渲染失败时前端直接用文本）；
  - 标签净化：换行合并为空格、`()[]{}<>` 转全角、截 40 字；节点顺序保持输入顺序；超过 80 节点截断并 `truncated=true`。

### 5.9 `create_review_plan`

- 用途：给一批知识点排一个未来 N 天的复习计划**建议**；只返回计划，不写 `review_items`（人工确认后由 S6-2/S6-5 落库）。
- input：`kp_ids: list[int]`（1–30，去重）、`days: int = 3`（1–14）。
- output：`days`、`timezone`、`items[]`、`by_day[]`、`total_minutes`
  - item：`kp_id`、`kp_name`、`day`、`date`、`planned_minutes`、`priority`、`mastery_t`、`reason`
  - by_day：`day`、`date`、`item_count`、`total_minutes`
- 行为：
  1) `mastery_service.mastery_details(...)`；
  2) 排序：已评估按 `M_t` 升序；未评估排最后按 `kp_id` 升序；
  3) 轮转分配：`day = index % days + 1`（第一天 = 本地「明天」，用 `review_service.local_bounds` 的 `Asia/Shanghai` 日界，避免与今日清单重复）；
  4) 每项 `planned_minutes = review_service.estimated_minutes("question", 3)`（6 分钟）；
  5) `priority = review_service.review_priority(M_t or 0.5, overdue_ratio, exam_weight)`；逾期程度用 `due_at` + `review_service.review_interval_days(stability, M_t)` 计算；无掌握度行时 `mastery_t=null`，`reason="尚未评估，建议先做一次练习"`；
  6) 不 `commit`，不写库。

### 5.10 `export_paper_pdf`

- 用途：给已保存试卷生成**受权校验后的下载地址**；供任务 B 最后一步使用。
- input：`paper_id: int`（≥1）、`variant: Literal["questions","answers"] = "questions"`。
- output：`paper_id`、`title`、`variant`、`question_count`、`total_score`、`filename`、`download_url`
- 行为：`paper_plan_service.get_paper(session, user_id=ctx.user.id, paper_id=...)` 校验存在与归属（不存在 404、非本人 403）；**不渲染 PDF、不读二进制**，只返回 `/api/v1/papers/{paper_id}/export.pdf?variant={variant}` 与 `试卷-{paper_id}-{题干卷|答案卷}.pdf`。S6-4 由前端/工具调用方真正下载。
- 说明：工具出参必须是 JSON，不能返回 PDF 字节；渲染仍走 S5-3 既有接口与单渲染线程。

### 5.11 `calculator`

- 用途：四则/乘方等算术求值，避免模型心算错误；不支持符号计算、函数、变量。
- input：`expression: str`（1–200）。
- output：`expression`、`value: float`、`text: str`（12 位有效数字）、`exact: bool`（结果是否为整数）。
- 行为：`ast.parse(expression, mode="eval")` + 白名单节点（`Expression`、`Constant` 且仅 int/float、`BinOp` 的 `+ - * / // % **`、`UnaryOp` 的 `+/-`）；拒绝 Name/Call/Attribute/Subscript/字符串/布尔/复数；`**` 指数绝对值 ≤100；除零 → `ToolInputError("不能除以 0")`；结果非有限 → `ToolInputError("计算结果超出范围")`。纯函数，无副作用。

## 6. 服务层最小增量（向后兼容）

| 文件 | 增量 | 兼容性 |
|---|---|---|
| `services/mastery_service.py` | 新增 `KpMasteryState` dataclass + `mastery_details(session, *, user_id, kp_ids, now=None)` | 只增不改；复用 `decayed_mastery`；现有 `list_mastery/mastery_values` 不动 |
| `services/question_service.py` | `QuestionFilters` 增 `kp_ids/difficulty/exclude_user_id/exclude_done_since`；`build_questions_query` 增条件 | 新字段默认 `None`，现有 API 调用 SQL 不变；`kp_ids` 用 `EXISTS` 防重复行 |
| `services/mistake_service.py` | `MistakeFilters` 增 `kp_ids` | 默认 `None`；多 kp 用 OR `EXISTS`，与单 `kp_id` 语义一致 |

不新增数据库表/列/迁移；不改 `API.md` 现有接口契约（工具不是 HTTP 接口）。`SCHEMA.md` 无需改；`docs/AGENT_TOOLS.md` 记录工具目录。

## 7. Prompt（`generate_questions`）

- 文件：`backend/app/ai/prompts/agent_gen_questions_v1.md`。
- 变量：`kp_name`、`subject_name`、`difficulty`、`difficulty_label`、`qtype`、`count`、`question_shape`（选项要求说明）。
- 约束（与 S4-4 同风格）：
  - 只输出严格 JSON `{"questions":[...]}`，不要 Markdown 代码围栏、不要解释；
  - 每题字段：`stem_md`、`options`（单选/多选给 ≥2 项，填空/解答为 `null`）、`answer_md`、`analysis_md`、`qtype`、`difficulty`；
  - LaTeX 反斜杠必须双写（`\\frac`），避免 JSON 非法；`analysis_md` 10–200 字；
  - 题目必须可独立作答，不引用原题；不得编造教材页码。
- 渲染失败/LLM 失败/校验失败均走统一重试与 `ToolExecutionError`；Prompt 不落日志正文。

## 8. 测试

### 8.1 单测清单（全部 mock 外部依赖）

| 文件 | 覆盖 |
|---|---|
| `test_agent_tools_registry.py` | 11 个工具名/顺序；描述非空且含「用途」；入参 `extra=forbid`；`invoke_tool` 未知工具 404、非法入参 422、意外异常 → 500 且不泄露堆栈 |
| `test_agent_tool_calculator.py` | 四则/优先级/负数/括号/整除/取模/乘方；非法 Name/Call/Attribute/字符串/布尔；除零；超大指数；非有限结果；`exact` |
| `test_agent_tool_make_mindmap.py` | 父子建树、边建树、环 → graph、多父 → graph、标签净化、80 节点截断、fallback 文本、顺序稳定 |
| `test_agent_tool_search_notes.py` | 透传 query/scope/top_k/retrieval；hit 截断标记；空 query 422；不返回 debug |
| `test_agent_tool_list_notes.py` | 日期窗口含当天；tags 过滤；limit 透传；多标签内存过滤；空结果 |
| `test_agent_tool_get_kp_subgraph.py` | depth=1/2 节点与边；中心必含；只取 approved；节点不存在 404；输出排序稳定 |
| `test_agent_tool_list_mistakes.py` | kp_ids/status/日期/limit 透传；字段映射；空结果 |
| `test_agent_tool_get_mastery.py` | 已评估/未评估/不存在三类 id；`M_t` 用固定 `now`；不冒充 0 |
| `test_agent_tool_search_questions.py` | kp_ids/qtype/difficulty/exclude_recent 透传；不返回答案；verified 优先排序；截断 |
| `test_agent_tool_generate_questions.py` | Prompt 渲染（StrictUndefined）；合法 JSON 成功；条数不符/非法 JSON 重试；重试耗尽 500；不写库；`attempts` |
| `test_agent_tool_create_review_plan.py` | 排序（低 M_t 先）、轮转分天、日期为明天、优先级公式、未评估兜底、无写库 |
| `test_agent_tool_export_paper_pdf.py` | 归属校验 404/403；URL/文件名；不渲染 |
| `test_agent_tools_schema_export.py` | 文件与现场生成一致；11 条；OpenAI 结构；outputs 覆盖全部工具 |
| `test_agent_tools_service_support.py` | `mastery_details` 的 M_t/缺失分类；`QuestionFilters` 新条件编译进 SQL 且旧调用 SQL 不变；`MistakeFilters.kp_ids` |

### 8.2 测试数据与隔离

- 沿用仓库惯例：service/工具用 fake session + monkeypatch service 函数；不连真实库、不发真实网络。
- `generate_questions` 用 fake `LLMClient`，断言 `scene="gen"` 与 `max_tokens=3500`。
- 固定 `now=2026-11-17T00:00:00Z`，避免时间漂移。

## 9. 验收与交付物

1. `pytest -q` 全绿（基线 1458 passed, 5 warnings；新增测试后如实记录总数）。
2. `python scripts/export_agent_tools.py` 生成 `backend/data/agent_tools.json`，测试校验一致。
3. `python scripts/agent_tools.py list` 列出 11 个工具；`schema` 打印与文件一致。
4. 真实库 + 真实用户（user 50）逐个 `call`：
   - 本地：`calculator`、`make_mindmap`、`list_notes`、`list_mistakes`、`get_mastery`、`get_kp_subgraph`、`search_questions`、`create_review_plan`、`export_paper_pdf`；
   - 外部：`search_notes`（Embedding/Rerank）、`generate_questions`（LLM，1 次，3 题草稿）。
   - 记录每个工具的实测入参/关键出参/耗时；失败如实记录。
5. 文档同步：`docs/AGENT_TOOLS.md` 新建；`docs/DECISIONS.md` 追加 D-065；`docs/PROGRESS.md` 更新 S6-1 状态与验收数字；`AGENTS.md §9.6` 追加工具层锚点。
6. Conventional Commit：`feat(s6-1): 实现 Agent 工具集与 schema 导出`；`git push` 由用户执行。

## 10. 风险与已知边界

- **任务卡「10 个」与方案 11 个不一致**：按用户确认采用 11 个并在文档注明。
- **「工具是纯函数」的字面口径**：DB/LLM 工具无法字面纯；本 spec 定义为「显式注入依赖、无隐藏状态、可回放」，真正的纯函数是 `calculator`/`make_mindmap` 与各工具的映射/排序辅助。
- **`get_kp_subgraph` 用全学科 snapshot**：当前 108 节点可接受；学科规模上千时需下沉 SQL。
- **`search_questions` 增强 `QuestionFilters`**：新增字段默认不启用，但改变了共享查询构造器；必须补「旧调用 SQL 不变」编译断言，防止组卷/题库列表回归。
- **`generate_questions` 复用 `gen` 场景**：用量统计无法把 Agent 补题与变式题分开；S6-2 如需区分再加 `agent` 场景迁移，本卡不加。
- **`export_paper_pdf` 不真正渲染**：工具只给受权下载地址；真实渲染失败仍由 S5-3 接口返回 500，Agent 步骤日志只能记录「链接已生成」。
- **`create_review_plan` 不写库**：S6-1 的「计划」是建议，与 S5-5 的 `review_items` 真实清单存在口径差；落库确认流程在 S6-2/S6-5。
- **多标签 `list_notes` 的 `total`**：服务端分页总数按第一个标签过滤，内存再过滤其余标签，页面内条数可能少于 `total`；文档写明，不为此改 S2-5 列表契约。

## 11. 契约影响

- `API.md`：无新增/修改（工具不是 HTTP 接口；Agent 三条接口仍等 S6-2 定稿）。
- `SCHEMA.md`：无表/列变更。
- 环境变量/依赖：无新增。
- `LLMCallScene`：无新增（复用 `gen`）。
- `docs/AGENT_TOOLS.md`：新增，记录 11 个工具的入参/出参/错误与 schema 再生成命令。