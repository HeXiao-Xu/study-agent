# API.md — 接口契约

> 来源：《个性化学习智能体-毕业设计完整方案.md》第 6 章 + 附录 B（接口草案），条目格式参照实施计划附录 B2。
> 本文件是前后端的**共同语言**，接口变更必须先改这里再写代码（AGENTS.md §8）。
> 规则：方案未写明的字段一律标 `TODO 待定`，禁止自行编造；每条接口标注权限与类型（同步 / 异步任务 / SSE 流式）。

## 0. 全局约定

- Base path：`/api/v1`；另有 `GET /health`（无前缀，S0-5 交付）
- 命名：路径与字段一律 `snake_case`（与数据库一致，**定死**）
- 认证：JWT（S2-2 交付）。未特别标注的接口权限默认 `student`，且只能访问自己的数据；⚠ RBAC 细则 S2-3 定稿
- 统一响应：`{code, message, trace_id, data}`（成功 `code=0`；错误结构与码表见 §13，S0-5 已落地）
- trace_id 透出：响应头 `X-Trace-Id` 一律返回；请求头可传 `X-Trace-Id` 续链（S0-5 定稿）
- 分页：列表接口统一分页参数（fastapi-pagination，S2-4 交付）
- SSE 与异步任务接口的轮询/推送约定：TODO（S3-5 / S2-7 定）

## 1. 认证

### POST /api/v1/auth/login
- 权限：公开
- 类型：同步
- 入参/出参：TODO 待定（S2-2 定稿）
- 备注：注册 / 登出 / refresh 等接口清单同样 TODO（S2-2 补充，方案未列）

## 2. 笔记

### GET /api/v1/notes
- 权限：student（仅本人数据）
- 类型：同步（分页）
- 入参：`subject` / `tag` / `q`（检索）/ `page`
- 出参：笔记列表（字段细节 TODO，S2-5）

### POST /api/v1/notes
- 权限：student
- 类型：同步
- 入参/出参：TODO（S2-5）
- 备注：单篇详情 / 更新 / 删除、笔记本（folder）管理接口方案未列，TODO（S2-5 补充）

## 3. 文件上传与解析

### POST /api/v1/files
- 权限：student
- 类型：同步返回 + 后台异步解析（S2-7 任务框架 / S2-8 解析 Worker）
- 入参：multipart 文件
- 出参：`file_id`
- 备注：按 `sha256` 去重（SCHEMA §9）

### GET /api/v1/files/{id}/parse-status
- 权限：student
- 类型：同步
- 出参：解析进度（`parse_status` + 进度细节 TODO）

## 4. 知识点

### GET /api/v1/kp/tree?subject=math
- 权限：student
- 类型：同步
- 出参：知识点树（knowledge_points 层级结构）

### POST /api/v1/kp/align/confirm
- 权限：student
- 类型：同步
- 说明：确认 AI 标注（对齐置信度 0.55–0.75 的待确认项，方案 6.2）
- 入参：TODO（S2-10）

## 5. RAG 问答（论文核心）

### POST /api/v1/qa/ask
- 权限：student
- 类型：SSE 流式
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | question | string | 是 | 用户问题，1–500 字 |
  | scope | object | 否 | {subject_id?, notebook_id?, start_date?, end_date?} |
  | conversation_id | string | 否 | 不传则新建会话 |

- SSE 事件：
  - `meta`：{citations:[{index,note_id,chunk_id,title,heading_path,page_no,snippet}]}
  - `delta`：{text:"..."}
  - `done`：{message_id, tokens, latency_ms, refused:bool}
- 错误码：401 未登录 / 403 无权访问该 scope / 429 超出频率限制 / 500 生成失败
- 备注：无检索依据时返回 refused=true 与固定拒答文案，不调用 LLM
- 检索链路与参数（方案 6.4）：向量 top-20 + 全文 top-20 → RRF（k=60）→ Rerank 取 top-6 → 上下文预算 4k–6k token；拒答阈值 τ=0.35（重排分归一化，需实测校准）；温度 0.3；多轮仅取最近 3 轮做 query 改写；缓存 (user_id, 规范化问题, scope) 24h

### GET /api/v1/qa/messages/{id}/citations
- 权限：student（仅本人消息）
- 类型：同步
- 出参：引用列表（对应 message_citations 表）

## 6. 错题本

### POST /api/v1/mistakes
- 权限：student
- 类型：同步
- 入参：题目 + 我的答案（`image_file_id` 可选，拍照录入）
- 出参：TODO（S4-2）

### POST /api/v1/mistakes/{id}/analyze
- 权限：student
- 类型：异步任务
- 说明：触发 AI 诊断；五维输出见方案 6.3（知识点定位 / 错因分类 6 类+unknown / 第一处错误步骤 / 变式训练 2–3 道 / 复习建议）
- 出参：任务受理结果（TODO，S4-3）

### GET /api/v1/mistakes/{id}/analysis
- 权限：student
- 类型：同步
- 出参：诊断结果（mistake_analyses 表）

## 7. 题目生成

### POST /api/v1/questions/generate
- 权限：student
- 类型：异步任务 ⚠（TODO 同步/异步 S4-4 定）
- 说明：生成后必须过「格式校验（LaTeX 可编译、选项齐全、答案在选项内）+ 独立复算」两道关，不一致丢弃或重生成（最多 2 次），通过后入库并标 `verified`（方案 6.5）
- 入参：TODO（S4-4）

## 8. 组卷与作答

### POST /api/v1/papers/generate
- 权限：student
- 类型：异步任务 ⚠（TODO S5-2 定）
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | kp_ids | array | 是 | 知识点覆盖清单 |
  | qtype_ratio | object | 是 | 题型配比 |
  | difficulty_dist | object | 是 | 难度分布（如 3:5:2） |
  | total_score | number | 是 | 总分 |

- 出参：试卷 JSON + 预览（题干与答案分离，方案 6.5）
- 备注：组卷为「约束满足 + 贪心打分」：掌握度 < 0.5 优先基础题、> 0.8 配难题、排除近 14 天做过的题

### GET /api/v1/papers/{id}/export.pdf
- 权限：student
- 类型：同步（Playwright 渲染）
- 出参：PDF 下载

### POST /api/v1/answers
- 权限：student
- 类型：同步
- 说明：提交作答 → 回写掌握度（方案 6.6：s = 1/0.5/0，K_eff = K0/difficulty，M ← clamp(M + K_eff·(s−M), 0, 1)；S 更新与 due_at 计算）
- 入参/出参：TODO（S5-4）

## 9. 复习与报告

### GET /api/v1/review/today
- 权限：student
- 类型：同步
- 出参：今日复习清单（priority = 0.5·(1−M_t) + 0.3·逾期程度 + 0.2·考纲权重；M_t < 0.4 天天出现；总量控制在 30–40 分钟，方案 6.6）

### GET /api/v1/reports/mastery?range=30d
- 权限：student
- 类型：同步
- 出参：掌握度数据（雷达图/热力图/学习轨迹所需，方案 6.8）

## 10. Agent

### POST /api/v1/agent/tasks
- 权限：student
- 类型：异步任务
- 入参：

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | type | string | 是 | "weekly_mindmap" \| "mistake_paper" |
  | input | object | 是 | 任务输入（结构随 type 定，TODO S6-3/S6-4） |

- 约束（方案 6.7）：最大步数 12；单任务 token 预算上限；工具入参 JSON Schema 校验；写操作必须经人工确认；全程步骤日志 + 引用收集

### GET /api/v1/agent/tasks/{id}
- 权限：student（仅本人任务）
- 类型：同步
- 出参：任务状态 + 步骤列表（agent_steps，支持回放）

### POST /api/v1/agent/tasks/{id}/confirm
- 权限：student
- 类型：同步
- 说明：人工确认（human-in-the-loop），任务从 waiting_confirm 继续

## 11. 运维

### GET /api/v1/admin/usage?range=7d
- 权限：admin ⚠（RBAC 细则 S2-3）
- 类型：同步
- 出参：用量统计（llm_call_logs 聚合：scene/model/tokens/cost/latency）

### GET /health
- 权限：公开
- 类型：同步
- 说明：无 `/api/v1` 前缀；S0-5 交付，健康检查

## 12. 待定接口清单（TODO，方案未列、对应任务定稿时补充）

| 模块 | 缺口 | 定稿任务 |
|---|---|---|
| 认证 | 注册 / 登出 / refresh / token 刷新策略 | S2-2 |
| 笔记 | 单篇详情 / 更新 / 删除、笔记本（folder）管理 | S2-5 |
| 知识点 | 树的导入与管理端接口 | S2-9 |
| 错题 | 列表 / 统计看板 | S4-2 / S4-8 |
| 复习 | 计划手动调整 | S5-5 |

## 13. 错误码表

S0-5 定稿（落地于 `backend/app/core/exceptions.py`）：

- 规则：`0` = 成功；错误码 = **HTTP 状态前 3 位 + 2 位序号**；业务码 6xxxx 起按模块分段（S2 各业务卡起用）
- trace_id 透出：响应头 `X-Trace-Id` 一律返回；请求头可传 `X-Trace-Id` 续链

| code | 含义 | HTTP |
|---|---|---|
| 40000 | 通用请求错误 | 400 |
| 40100 | 未认证 | 401 |
| 40300 | 无权限 | 403 |
| 40400 | 资源不存在 | 404 |
| 42200 | 参数校验失败 | 422 |
| 42900 | 限流 | 429 |
| 50000 | 服务器内部错误 | 500 |

---

> 维护规则（AGENTS.md）：接口变化必须同步本文件；前后端字段命名以本文件为准（snake_case）；与本文件冲突的实现视为 bug。
