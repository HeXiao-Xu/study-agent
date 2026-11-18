# 周笔记导图（S6-3）

> 代码：`backend/app/ai/agents/tasks/weekly_mindmap.py`、`backend/app/ai/prompts/weekly_mindmap_v1.md`、`web/src/views/agent/WeeklyMindmap.vue`
> 前置：S6-1 工具集、S6-2 状态机；决策 D-067。S6-4（错题组卷 Agent）不做。

## 1. 任务流程

```text
plan: list_notes(过去 N 天)
  ↓ 动态扩展
get_kp_subgraph × 最多 3 个（按笔记知识点频次取 top3）
  ↓ 动态扩展
LLM 聚类（scene=agent，严格 JSON；失败降级）
  ↓ 动态扩展
make_mindmap → Mermaid + fallback 文本
  ↓
finalize：summary_md + citations + degraded → agent_tasks.result_json
```

- 动态规划：S6-2 引擎新增 `AgentTaskSpec.extend_plan(state)`，observe 成功后按已有产物追加下一步；不新增图节点。
- 步数：plan(1) + list_notes(2) + 3 子图(6) + make_mindmap(2) + finalize(1) = 12，正好上限；少知识点更少。空窗口只跑 list_notes + finalize（4 行）。
- 结果只写 `agent_tasks.result_json`，**不新建笔记**；前端按 task id 读取。

## 2. 输入与结果

```json
// POST /api/v1/agent/tasks
{"task_type": "weekly_mindmap", "input": {"days": 30, "subject_id": null}}
```

`days` 1–30（默认 7）；`subject_id` 可选。

结果字段：

| 字段 | 说明 |
|---|---|
| `task_type` | `weekly_mindmap` |
| `days` / `note_count` / `kp_count` | 窗口、笔记数、去重知识点数 |
| `summary_md` | 分支标题 + 结论 + `（引用：笔记 #id）`；空窗口为固定文案 |
| `mermaid` | Mermaid mindmap 文本；空窗口为空串 |
| `fallback_text` | 纯文本结构树（前端渲染失败时展示） |
| `citations` | `[{note_id,note_title}]`，只含输入笔记 |
| `degraded` | LLM 聚类失败/校验失败时为 true，结构按知识点降级 |
| `cluster_prompt_version` | `weekly_mindmap_v1` |

## 3. LLM 聚类

- 输入：笔记 `{note_id,title,preview,kp_names}` + 子图 `{nodes,edges}`。
- 输出：`{title, branches:[{kp_id,title,conclusion,note_ids,children}]}`；1–8 分支、引用必须来自输入笔记、kp_id 必须来自子图。
- 严格 JSON、最多 2 次重试（共 3 次调用）；仍失败 → 按 `kp_names` 分组的确定性树，`degraded=true`，任务仍成功。
- 用量：`scene=agent`，token 通过 `PlanExtension.token_cost` 累加到 `agent_tasks.token_cost`；预算默认 20000。

## 4. 前端页面

路由 `/agent/mindmap/:taskId?`，导航「学习导图」：

- 无 taskId：选天数（默认 7）→「生成导图」→ POST → 跳转任务 URL。
- 有 taskId：1 秒轮询 GET；运行中显示状态与步骤数。
- 成功：摘要用 `MdPreview` 渲染 Markdown、引用标签、Mermaid SVG；`note_count=0` 显示空态；`degraded` 显示降级提示。
- Mermaid 渲染失败：显示 `fallback_text` 结构树，不白屏。
- 「导出 PNG」：SVG → Canvas（2×、白底）→ PNG，文件名 `学习导图-{taskId}-{date}.png`。
- Mermaid 初始化 `htmlLabels:false`：避免 `foreignObject` 让 Canvas 被标记为 tainted，导致导出失败（验收中实际踩到并修复）。

## 5. 验收口径与缺口

- 真实库 user 18（test1）只有 4 篇笔记，日期 2026-10-27/29；今天 2026-11-17。
- **7 天窗口**：`note_count=0`、固定空文案、无导图（任务卡「真实 7 天笔记」因数据缺口未满足，不造假）。
- **30 天窗口**：4 篇笔记、2 个知识点；真实 LLM 未降级，10 步、token 2296、约 15.1 s，Mermaid 与 4 条引用齐全。
- 前端 Chrome 1440×900：导图 SVG 可见、导出 PNG 220,037 B、空态正常、页面生成 30 天任务成功、无横向溢出/console error。

## 6. 已知边界

- 7 天真实数据缺口（S7-6 种子数据可补）；聚类语义正确性只做目测，不保证。
- 最多 3 个知识点子图（再多会撞 12 步上限）；不做 `max_kps` 配置。
- LLM 降级时分支只按知识点/笔记标题分组，不含语义结论。
- Mermaid 包较大（构建 chunk 约 647 kB），随路由懒加载。
- 导出依赖浏览器 Canvas 与 SVG 内嵌字体；系统字体栈下目测正常，不保证跨机器字体一致。
- 导图只存在任务结果里，无历史列表/回收站（S6-5/S6-6 后续）。
- `mistake_paper` 不注册：用户 2026-11-17 决定 S6-4 不做（组卷已有 S5-1/S5-2）。