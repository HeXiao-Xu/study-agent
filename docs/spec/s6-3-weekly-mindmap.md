# S6-3 任务 A：周笔记整理 + 思维导图（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S6-3。产出 `ai/agents/tasks/weekly_mindmap.py`、前端导图页。
> 方案依据：`docs/个性化学习智能体-毕业设计完整方案.md` §6.7 任务 A。
> 前置：S6-2 状态机/步骤持久化、S6-1 工具集已交付。
> 范围：weekly_mindmap 任务类型（动态规划 + LLM 聚类 + Mermaid + 摘要/引用）+ 前端导图页/PNG 导出。
> 状态：**已确认**（2026-11-17）。实现按 `docs/plan/s6-3-weekly-mindmap.md` 执行。
> **S6-4 跳过**：用户 2026-11-17 决定不做错题组卷 Agent（组卷已由 S5-1/S5-2 实现），`mistake_paper` 不注册。

## 1. 目标与非目标

### 1.1 目标

1. 新增 `weekly_mindmap` 任务类型：`list_notes(过去 N 天)` → `get_kp_subgraph`（涉及知识点，≤3 个）→ LLM 按知识点聚类 → `make_mindmap` → 结果落 `agent_tasks.result_json`。
2. 同时产出「上周学习摘要」：分支标题 + 关键结论 + 引用（note_id/标题），不编造输入中不存在的内容。
3. LLM 聚类失败（JSON 非法/重试耗尽）时**降级**为按知识点/笔记标题的确定性结构树，任务仍成功并标 `degraded=true`；Mermaid 渲染失败时前端显示 `fallback_text` 纯文本树。
4. 前端新增「学习导图」页：生成（选天数）→ 轮询任务 → Mermaid 渲染 → 导出 PNG；无任务 id 时可发起，有 id 时按 URL 加载。
5. 后端扩展状态机支持**动态规划**：`AgentTaskSpec.extend_plan(state)` 在每个 observe 成功后按已有产物追加下一步（不新增图节点），仍受最大步数 12 约束。
6. `list_notes` 工具补充 `preview/kp_ids/kp_names`，让聚类有内容与知识点可用（不新增工具）。
7. 测试覆盖引擎动态规划、工具增量、聚类适配器（成功/非法 JSON/降级）、weekly spec 全流程、前端渲染/导出/空态；真实库跑一次（含 7 天空窗口与 30 天有数据两种情况，禁止造假）。

### 1.2 非目标

- 不做 `mistake_paper`（S6-4 跳过）。
- 不做任务列表/任务详情通用页（S6-5）；本轮只有 `/agent/mindmap/:taskId?` 专用页。
- 不自动新建笔记、不写 `notes`/`note_kps`；结果只存 `agent_tasks.result_json`。
- 不做 SSE；前端 1 秒轮询。
- 不做服务端 Mermaid 渲染/PDF；导出 PNG 在前端用 Canvas 完成。
- 不改 S6-1 的 11 个工具清单（`list_notes` 只扩出参，不新增工具）。
- 不引入第二个前端渲染库；只加 `mermaid@^11`（已安装 11.17.2）。

## 2. 用户已确认的决策（2026-11-17）

| # | 决策 | 选择 |
|---|---|---|
| D1 | Mermaid 依赖 | 批准安装 `mermaid@^11`（实际 11.17.2），只用于前端渲染与 SVG→PNG |
| D2 | 落库位置 | 只写 `agent_tasks.result_json`（导图/摘要/引用）；不新建笔记、不做写操作确认 |
| D3 | 页面入口 | 新增导航「学习导图」+ 路由 `/agent/mindmap/:taskId?`；无 id 时显示生成表单，有 id 时加载任务 |
| D4 | S6-4 | 不做（组卷已有 S5-1/S5-2）；`mistake_paper` 不注册 |
| D5 | 空窗口 | 过去 N 天没有笔记时任务成功，返回 `note_count=0` + 固定文案，不生成空导图 |
| D6 | 聚类降级 | LLM 失败不把任务判失败：按知识点/笔记标题生成确定性树，`degraded=true`，摘要注明「聚类降级」 |

## 3. 后端设计

### 3.1 状态机动态规划扩展

`ai/agents/engine.py` 增加：

```python
@dataclass(frozen=True)
class PlanExtension:
    steps: list[PlanStep] = field(default_factory=list)
    token_cost: int = 0
    thought: str | None = None
```

- `AgentTaskSpec` 增加 `extend_plan(self, state) -> PlanExtension`（demo 返回空扩展）。
- `observe` 成功后（无 `last_error`）：
  1) 把本步产物写入 artifacts / `current_index+1`；
  2) 调 `spec.extend_plan(prospective_state)`；
  3) 有 `steps` 则 `plan.extend(steps)`（下一步路由到 `act`）；`token_cost>0` 则累加并做预算检查；
  4) observe 行 thought 记录扩展摘要（如「追加 2 个知识点子图」）。
- 不新增图节点；扩展仍在 observe 行内完成，不额外消耗步骤数。若扩展后步数将超过 12，下一次 `act` 的 guard 会抛 `AgentStepLimitError`，任务失败并写清原因。
- `extend_plan` 必须**幂等/可重入**：仅依据 `state.plan` 已含工具与 `state.artifacts` 判断阶段，不能依赖实例字段（崩溃恢复会新建 spec 实例）。

### 3.2 `list_notes` 出参扩展（向后兼容）

在 `ListNotesOut.items[]` 增加：

| 字段 | 类型 | 说明 |
|---|---|---|
| `preview` | string\|null | `notes.content_text` 前 200 字（给聚类用，避免拉全文） |
| `kp_ids` | int[] | 该笔记挂载的知识点（`note_kps`，最多 10 个；confirmed 优先、kp_id 稳定排序） |
| `kp_names` | string[] | 对应知识点名 |

实现：现有分页查询后，新增两条 `IN` 批查（`notes.content_text`、`note_kps join knowledge_points`），禁止逐条查库；两个查询都不改 `note_service.list_notes` 的契约。空列表不发查询。

### 3.3 `weekly_mindmap` 任务类型

`ai/agents/tasks/weekly_mindmap.py`：

- 输入模型（`extra="forbid"`）：
  - `days: int = 7`（1–30）
  - `subject_id: int | null`（可选，传给 `list_notes`）
- `task_type="weekly_mindmap"`、`requires_confirm=False`。
- `build_plan(state)`：按 `now`（注入，默认 UTC 当前时间）算本地/UTC 日期窗口，返回 `list_notes` 一步：
  ```json
  {"tool":"list_notes","input":{"start_date":"2026-11-11","end_date":"2026-11-17","subject_id":7,"limit":50},"purpose":"取过去 7 天笔记"}
  ```
  - `limit=50`（工具上限）；`start = today-(days-1)`、`end = today`（UTC）。
- `extend_plan(state)` 三阶段（按 `state.plan` 已含工具判断）：
  1) **无 `get_kp_subgraph` 且笔记有知识点**：统计 `kp_ids` 频次，取 top 3（同频按 `kp_id ASC`），追加 3 个 `get_kp_subgraph(kp_id, depth=1)`；无知识点则直接进第 2 阶段。
  2) **无 `make_mindmap`**：用笔记（标题/preview/kp_names）+ 子图（节点/边）调 LLM 聚类；把聚类结果转成 `make_mindmap` 的 nodes/edges 计划（根标题 + 分支 + 子节点），追加 1 步。
  3) **已有 `make_mindmap`**：返回空扩展。
  - 空笔记（`note_count=0`）：不再扩展，直接 finalize 空结果。
  - 同一次运行里最多 3 个子图 + 1 个导图，步骤行数：plan(1)+list(2)+3×子图(6)+导图(2)+finalize(1)=12，正好卡上限；空/少知识点时更少。
- `finalize(state)` 组装结果（写 `agent_tasks.result_json`）：

```json
{
  "task_type": "weekly_mindmap",
  "days": 7,
  "note_count": 4,
  "kp_count": 2,
  "summary_md": "## 上周学习摘要\n- 函数的单调性：……（引用：笔记 #54）",
  "mermaid": "mindmap\n  root((...))...",
  "fallback_text": "- 上周学习\n  - 函数...",
  "citations": [{"note_id":54,"note_title":"..."}],
  "degraded": false,
  "cluster_prompt_version": "weekly_mindmap_v1"
}
```

  - 空窗口：`note_count=0`、`summary_md="过去 N 天没有笔记，先记录一些学习内容再来生成导图。"`、`mermaid=""`、`citations=[]`、`degraded=false`。
  - 摘要只使用聚类输出中的分支标题/结论与输入笔记标题；每条结论末尾附 `（引用：笔记 #id、#id）`；引用列表去重。
  - Mermaid 与 fallback 由 `make_mindmap` 工具产出，工具失败按普通工具失败重试；最终仍失败则任务 failed（不是降级）。

### 3.4 LLM 聚类

- Prompt：`backend/app/ai/prompts/weekly_mindmap_v1.md`（Jinja2 `StrictUndefined`）。
- 适配器：`ai/agents/tasks/weekly_mindmap.py` 内 `generate_cluster(context, *, llm_client=None, max_retries=2)`。
- 输入上下文：`days`、笔记列表 `{note_id,title,preview,kp_names}`、子图 `{nodes:[{kp_id,name}],edges:[{src,dst,relation}]}`。
- 输出严格 JSON：

```json
{
  "title": "上周学习导图",
  "branches": [
    {"kp_id": 137, "title": "函数的单调性", "conclusion": "……",
     "note_ids": [54], "children": ["定义法", "图像法"]}
  ]
}
```

- Pydantic 校验：`title` 1–60；`branches` 1–8；`title/conclusion` 1–200；`note_ids` 必须 ⊆ 输入笔记 id；`kp_id` 必须是候选 kp 之一（可为 null）；`children` 0–6 个、每个 1–40 字。
- `scene="agent"`、`max_tokens=2200`、`temperature=0.3`；失败重试 2 次。
- 重试耗尽/JSON 非法 → **降级**：按 `kp_names` 分组（无 kp 按「学习笔记」一组），分支标题=知识点名，结论=`本周记录了 N 篇相关笔记`，children=笔记标题；`degraded=true`；不抛异常。
- token 用量通过 `PlanExtension.token_cost` 累加到任务的 `token_cost`。

### 3.5 注册与 API

- `TASK_SPECS` 增加 `weekly_mindmap`；`demo` 保留。
- `POST /agent/tasks` 现在接受 `weekly_mindmap`（输入 `{days,subject_id}`），其余接口不变；`mistake_paper` 仍 422「任务类型尚未启用」。
- `GET /agent/tasks/{id}` 的 `result` 直接给上面的 JSON；前端按 `task.status` 与 `result.mermaid` 渲染。
- `API.md §10` 更新：任务类型改为 `demo`（验收）+ `weekly_mindmap`（S6-3）；注明 `mistake_paper` 不做。

## 4. 前端设计

### 4.1 依赖与文件

- `mermaid@^11`（11.17.2）写入 `package.json`/`package-lock.json`。
- 新增：
  - `web/src/api/agent.ts`：`createAgentTask(payload)`、`getAgentTask(id)`（沿用 `http.ts`）。
  - `web/src/types/agent.ts`：`AgentTask`/`AgentStep`/`WeeklyMindmapResult`。
  - `web/src/views/agent/WeeklyMindmap.vue`：页面。
  - `web/src/views/agent/mermaid.ts`：`renderMermaid(code)`（初始化 + `mermaid.render`），失败向上抛。
  - `web/src/views/agent/exportMindmap.ts`：`parseSvgSize(svg)` 纯函数 + `downloadSvgAsPng(svg, filename)`（SVG→Image→Canvas→PNG）。
  - `web/src/layouts/nav.ts` 加「学习导图」（`/agent/mindmap`）。
  - `router/index.ts` 加 `/agent/mindmap/:taskId(\\d+)?`（student）。
- 不动 S6-5 的通用任务页。

### 4.2 页面行为

- 无 `taskId`：表单（天数 1–30，默认 7）→「生成导图」→ POST → `router.replace` 带 taskId → 轮询。
- 轮询 1 秒；终态（succeeded/failed/waiting_confirm）停止；卸载时清定时器。
- 运行中显示状态与已生成步骤数（来自 GET `steps_count`）。
- `succeeded`：
  - `note_count=0` → 空态文案，不渲染 Mermaid。
  - 有 `mermaid` → `renderMermaid` 渲染 SVG；异常 → 显示 `fallback_text` 纯文本树 + 提示「导图渲染失败，已降级为结构树」。
  - 摘要 `summary_md` 用等宽/预格式文本展示；引用列表显示笔记 id + 标题。
  - `degraded=true` 显示「LLM 聚类失败，已按知识点降级」。
  - 「导出 PNG」按钮：`downloadSvgAsPng`，文件名 `学习导图-{taskId}-{YYYY-MM-DD}.png`；导出失败弹错误。
- `failed`：显示 `error`；`waiting_confirm` 本任务不会出现（兜底提示）。

### 4.3 导出 PNG

- `parseSvgSize(svgText)`：从 `<svg width height>` 或 `viewBox` 解析；缺失/0 抛错。
- `downloadSvgAsPng`：`Blob(svg, image/svg+xml)` → `URL.createObjectURL` → `Image` → canvas（2× 缩放、白底）→ `toBlob('image/png')` → `<a download>`。
- 不新增截图/导出依赖；沿用 S5-7 的 Canvas 思路。
- 单测：`parseSvgSize` 三种输入、文件名、无 SVG 抛错；页面测试 mock `renderMermaid`/`downloadSvgAsPng`。

## 5. 测试

| 文件 | 覆盖 |
|---|---|
| `test_agent_engine_extension.py` | `extend_plan` 追加步骤后继续 act；token_cost 累加；空扩展走 finalize；扩展导致超步数时失败 |
| `test_agent_tool_list_notes.py`（改） | preview/kp_ids/kp_names 两条批查；空列表不查；旧字段不变 |
| `test_agent_task_weekly_mindmap.py` | 输入校验；build_plan 日期窗口；extend_plan 三阶段（0/2/3 个 kp）；聚类成功建 nodes/edges；非法 JSON 重试后降级；finalize 摘要/引用/空窗口 |
| `test_agent_weekly_cluster.py` | Prompt 渲染；Pydantic 校验（越界 note_ids/kp_id/条数）；重试；token 返回 |
| `test_agent_service.py`（改） | 注册 weekly_mindmap 后可创建；mistake_paper 仍 422 |
| `test_agent_mindmap_api.py` | weekly 创建 202、GET result、days 越界 422 |
| 前端 `WeeklyMindmap.spec.ts` | 表单生成、轮询终态、Mermaid 成功、渲染失败降级、空窗口、导出按钮调用 |
| 前端 `mermaid.spec.ts` / `exportMindmap.spec.ts` | 渲染初始化/失败；`parseSvgSize`；文件名；空 SVG 抛错 |
| 前端 `agent.spec.ts` | API 封装路径/方法/壳 |

- 聚类测试全部 fake LLM，不真调；真实 LLM 放在验收。
- 前端 mock `mermaid`（大包，jsdom 不可真渲染），页面测试注入 mock。

## 6. 验收

### 6.1 自动化

- 后端 `pytest -q` 全绿（S6-2 基线 1543 passed）。
- 前端 `npm run test:run`、`npm run build`（vue-tsc + vite）全绿。

### 6.2 真实库（不造假数据）

当前真实库 user 18（test1）只有 4 篇笔记，全部在 2026-10-27/29；今天 2026-11-17。

1. **7 天窗口**：POST `weekly_mindmap {"days":7}` → 任务成功、`note_count=0`、固定空文案、无 mermaid；页面显示空态。如实记录「7 天无笔记，未生成导图」。
2. **30 天窗口**：POST `{"days":30}` → 真实 LLM 聚类 + 2 个知识点子图 + 导图；GET 检查 steps（≤12）、`result.mermaid`、`summary_md`、`citations`（只含 4 篇真实笔记）、`degraded=false`；记录 LLM 耗时/token。
3. 若真实 LLM 输出不合格导致降级，如实记录 `degraded=true` 与原因，不粉饰。
4. 前端 Chrome 1440×900：从 `/agent/mindmap` 生成 30 天任务 → 轮询 → 导图 SVG 可见 → 导出 PNG 文件非空；7 天空态；渲染失败时降级文本（可用 mock/构造验证）。
5. 证据 `.sdd/s6-3/acceptance-evidence.md` 区分「7 天任务卡口径未满足（真实库无近期笔记）」与实测结果。

## 7. 风险与已知边界

- **真实库 7 天无笔记**：任务卡「对真实 7 天笔记跑一次」无法满足；不造数据，改用 30 天真实笔记验收并记录缺口（S7-6 种子数据可补）。
- **动态规划步数**：3 个知识点 + 导图正好 12 行；再多一个知识点就会超上限失败。`max_kps` 固定 3，不做配置。
- **聚类质量**：LLM 可能分组不合理或引用错误；Pydantic 过滤非法 note_id，但语义正确性靠验收目测，不保证。
- **Mermaid 包体积**：11.x 较大；页面路由懒加载，构建包会增大（记录 gzip 体积）。
- **前端导出**：SVG 含外部字体/样式时 Canvas 可能缺字；使用系统字体栈，验收目测。
- **结果不落笔记**：导图只存在任务结果里，任务删除/清理后不可找回（S6-6/后续回收站）。
- **`list_notes` 出参扩展**：旧字段不变，新增字段可空；前端旧页面不读新字段。
- **LLM 费用**：每次生成最多 3 次聚类调用（2 次重试），scene=agent；预算默认 20000 足够。

## 8. 契约影响

- `API.md §10`：任务类型补 `weekly_mindmap`，说明 `mistake_paper` 不做；`result` 结构补 weekly 字段。
- `SCHEMA.md`：无表/列变更（复用 `agent_tasks.result_json/state_json`）。
- `AGENT_TOOLS.md`：`list_notes` 出参加 `preview/kp_ids/kp_names`。
- 前端依赖：`mermaid@^11`（11.17.2）写入 `package.json`/lock。
- 后端依赖：无新增（LLM 走既有适配器）。
- `llm_call_logs.scene`：复用 `agent`（CHECK 已有），无需迁移。
- PROGRESS：S6-3 完成；S6-4 标注「用户决定不做」；下一步 S6-5。