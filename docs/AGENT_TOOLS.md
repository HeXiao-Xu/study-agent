# Agent 工具目录（S6-1）

> 来源：方案 §6.7「工具清单」。代码在 `backend/app/ai/agents/tools/`，schema 文件 `backend/data/agent_tools.json`。
> 本卡只交付工具层；LangGraph 状态机、`agent_tasks/agent_steps`、Agent API 属于 S6-2。
> 所有工具**只读**：不 `commit`、不写 `questions`/`review_items`/`agent_*`。写操作必须等 S6-2 的人工确认流程。

## 1. 调用契约

```python
from app.ai.agents.tools import ToolContext, TOOLS, invoke_tool

ctx = ToolContext(session=session, user=current_user)  # now 默认 UTC 当前时间，可注入
out = invoke_tool("get_mastery", ctx, {"kp_ids": [117, 120]})
```

- `invoke_tool(name, ctx, payload)`：按名字取 `ToolSpec` → 用 Pydantic 入参模型校验（`extra="forbid"`）→ 调 handler → 返回出参模型。
- 未知工具 → `404/40400`；入参非法 → `422/42200`；工具内部意外异常统一 `500/50000`「工具 X 执行失败」，堆栈只进日志。
- 工具描述同时作为 LLM function description 导出到 schema 文件。

## 2. 工具清单（11 个）

| # | 工具 | 用途 | 主要入参 | 主要出参 | 外部依赖 |
|---|---|---|---|---|---|
| 1 | `search_notes` | 个人知识库混合检索，返回可引用片段 | `query`、`subject_id/folder/start_date/end_date/chunk_types`、`top_k`、`retrieval` | 命中列表（note_id/标题/页码/正文截 1200 字） | Embedding/Rerank（真实库验收 677 ms） |
| 2 | `list_notes` | 按时间/标签/学科列笔记元数据 | `start_date/end_date`、`tags`、`subject_id`、`limit` | 标题/标签/文件夹/时间 + 前 200 字预览 + kp_ids/kp_names（不含正文） | 无 |
| 3 | `get_kp_subgraph` | 取知识点 N 跳前置/相关/包含关系 | `kp_id`、`depth`（1–3） | 节点（含本人 `M_t`）+ 已审核边 | 图谱 snapshot |
| 4 | `list_mistakes` | 按知识点/状态/时间筛本人错题 | `kp_ids`、`status`、日期、`limit` | 题干片段/状态/题型/难度/知识点/错因 | 无 |
| 5 | `get_mastery` | 批量取本人掌握度 `M_t` 与到期时间 | `kp_ids`（1–50） | `assessed/unassessed/missing` 三类 + 每 kp 状态 | 无 |
| 6 | `search_questions` | 题库取材，只给题干不给答案 | `kp_ids`、`qtype`、`difficulty`、`exclude_recent_days`、`limit` | 题干（截 2000 字）/选项/题型/难度/知识点 | 无 |
| 7 | `generate_questions` | 题库不足时生成题目草稿（不入库） | `kp_id`、`difficulty`、`count`、`qtype` | 题干/选项/答案/解析 + `attempts` | LLM（`scene=gen`，最多 3 次调用） |
| 8 | `make_mindmap` | 节点/边 → Mermaid 思维导图 + 纯文本降级 | `title`、`nodes`、`edges` | `mermaid`、`fallback_text`、`mode` | 无（纯函数） |
| 9 | `create_review_plan` | 未来 N 天复习计划建议（不写库） | `kp_ids`（1–30）、`days`（1–14） | 逐项日期/优先级/理由 + 每日汇总 | 无 |
| 10 | `export_paper_pdf` | 校验试卷归属后给下载地址 | `paper_id`、`variant` | 文件名、`/api/v1/papers/{id}/export.pdf` 地址 | 无（不渲染 PDF） |
| 11 | `calculator` | 算术求值，避免模型心算错误 | `expression`（数字与 `+ - * / // % **`） | `value`、`text`（12 位有效数字）、`exact` | 无（纯函数） |

## 3. schema 导出与再生成

```bash
# 仓库根目录
python scripts/export_agent_tools.py
# 输出 backend/data/agent_tools.json：
# {"version":1, "tools":[{"type":"function","function":{name,description,parameters}}...], "outputs":{...}}
```

- 测试 `backend/tests/test_agent_tools_schema_export.py` 断言仓库文件与现场生成完全一致；改了工具入参/描述后必须重新运行脚本并提交 JSON。
- 结构兼容 OpenAI/DeepSeek 的 `tools` 入参；`outputs` 仅作文档与前端展示，不参与 function calling。

## 4. 独立 CLI

```bash
python scripts/agent_tools.py list                 # 11 行：名称 + 用途
python scripts/agent_tools.py schema               # 打印与文件一致的 JSON
python scripts/agent_tools.py call --user-id 50 calculator '{"expression":"2**10"}'
python scripts/agent_tools.py call --user-id 50 get_mastery '{"kp_ids":[116,117,120]}'
```

- `call` 从 `app.core.db.new_session()` 取真实库会话，回表取 User 后调用；业务错误打印 `code\tmessage` 并退出 1。
- 日志（jieba/httpx/llm_call）走 stdout，脚本化解析时要过滤；CLI 是验收入口，不是 Agent 运行链路。

## 5. 错误与边界

- 入参上限：`top_k ≤20`、`limit ≤50`、`kp_ids ≤50`、`depth ≤3`、`count ≤5`、`days ≤14`；超限 422，不静默截断。
- 文本截断：检索正文 1200 字、题干 2000 字、标签 40 字；出参带 `truncated`。
- 未评估 ≠ 0：`get_mastery`/`get_kp_subgraph`/`create_review_plan` 对无掌握度行返回 `null`，不冒充 0。
- `get_kp_subgraph` 用整学科 snapshot 后内存 BFS（当前 108 节点）；学科上千节点时再下沉 SQL。
- `search_questions` 默认排除本人最近 14 天做过的题（与 S5-1 组卷同口径）；真实库中该学科 4 道函数题都在窗口内，默认会得到 0 条，传 `exclude_recent_days=0` 可关闭。
- `generate_questions` 复用 `llm_call_logs.scene='gen'`，不新增迁移；草稿需人工确认后才可入库（S6-2/S6-4）。
- `export_paper_pdf` 只给地址，不读 PDF 字节；真实导出仍由 S5-3 的 `/papers/{id}/export.pdf` 完成。
- `create_review_plan` 是建议，不是 `review_items` 的真实清单；落库确认在后续卡。

## 6. 测试

| 文件 | 内容 |
|---|---|
| `tests/test_agent_tools_registry.py` | 11 个工具顺序、`write=False`、未知工具 404、非法入参 422、意外异常 500 |
| `tests/test_agent_tool_*.py` | 每个工具独立单测（含纯函数、透传、截断、重试与不写库） |
| `tests/test_agent_tools_service_support.py` | `mastery_details` 与两个 filters 增量的 SQL/返回值 |
| `tests/test_agent_tools_schema_export.py` | 11 条 OpenAI function、仓库文件不漂移 |

全部用例不连真实库、不发网络；`generate_questions` 用 fake LLM 断言 `scene/max_tokens`。