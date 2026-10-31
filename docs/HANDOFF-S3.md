# S3 启动交接（2026-10-31）

> 用途：新会话进入 S3 前先读本页，避免重新摸索代码与文档。
> 本页是**交接快照**，接口契约仍以 `docs/API.md` 为准，进度以 `docs/PROGRESS.md` 为准。

## 1. 当前基线

- 分支/提交：`master` @ `1b48f3c feat(ui): 教师/管理员笔记文件展示暂不支持占位`
- 已完成阶段：S0、S1、S2 全部任务（S2-14 已验收）
- 测试基线：
  - 后端 `524 passed, 1 warning`（warning 为 Starlette/httpx 既有弃用提示）
  - 前端 `85 passed / 20 files`
  - `npm run build` 退出 0（既有 >500 kB chunk 警告）
- 当前数据库：学科 `高中数学`（id 7）108 个知识点；3 篇原有笔记；账号 `test1`（student）、`teacher_demo`（teacher）
- 本地入口：前端 `http://localhost:5173`，后端 `http://127.0.0.1:8000`
- 未打 tag：`m1-framework-done`。任务卡要求库内有 20 篇真实笔记 + 1 份试卷，目前只有 3 篇原有笔记；不要用临时数据冒充。

## 2. 已交付能力

### 后端

- JWT 登录/注册、RBAC、学生私有数据隔离
- 笔记 CRUD、分页/筛选/排序、软删除
- 文件上传（MinIO、sha256 去重、大小/类型校验）、ARQ 异步解析任务
- 文档解析 Worker：Docling 解析 → 切片 → Embedding → `note_chunks`
- 知识点树 CRUD/导入/排序/跨级移动、知识点对齐任务与待确认队列
- 统一响应壳、trace_id、错误码、健康检查

### 前端

- 登录、主布局、路由守卫、角色登录落点
- 笔记列表/编辑、文件上传/解析状态/切片预览
- `/knowledge` 知识点树管理 + 待确认对齐单卡队列（教师/管理员可编辑，学生只读）
- 教师/管理员点「笔记」「文件」显示「暂不支持查看」占位（`StudentOnlyView`），不跳 403；学生页面不变

## 3. S3 可直接复用的 RAG 资产

| 资产 | 位置 | 说明 |
|---|---|---|
| 入库编排 | `backend/app/services/indexing.py` → `index_chunks()` | 切片 → Embedding → 覆盖写 `note_chunks`；S2-8 Worker 已在用，S3-1 必须复用，禁止另写 |
| 混合检索 | `backend/app/ai/rag/retriever.py` → `retrieve_hybrid_reranked()` | 向量 + 全文 + RRF + rerank；参数来自配置 |
| 上下文组装 | `backend/app/ai/rag/prompt_builder.py` | 预算、引用编号、上下文拼接 |
| 带引用回答 | `backend/app/ai/rag/answerer.py` → `answer_question()` | 已有拒答/引用结果对象，S3 服务层包一层，不要重写 |
| Prompt 初版 | `backend/app/ai/prompts/qa_v1.md` | S3-4 要迁到 `prompt_templates` 表并支持版本 |
| 命令行验收 | `scripts/ask.py`、`scripts/retrieval_eval.py` | 可先用真实问题验证服务化前后结果一致 |
| 评测 | `eval/run.py`、`eval/configs/*.json`、`eval/datasets/qa_set.jsonl` | S3-9 扩到 API 链路；已有三配置结果在 `eval/results/` |

## 4. S3 任务起点与缺口

按任务卡顺序做，不要跳：

1. **S3-1 索引服务产品化**：现有 Worker 已调用 `index_chunks`，但还没有独立 `services/index_service.py`、管理员重建索引接口、进度查询；笔记编辑后的重新索引链路也要定义。
2. **S3-2 检索服务**：把 `retrieve_hybrid_reranked` 封装成服务，补空知识库/scope 过滤/调试信息/延迟测试。
3. **S3-3 Query 改写**：新增 `services/query_rewrite.py`、`prompts/rewrite_v1.md`；意图仅 4 类；多轮合并最近 3 轮；闲聊不检索。
4. **S3-4 Prompt 版本管理**：`prompt_templates` 在 `SCHEMA.md §8.3` 有表设计，但**尚无 model/migration/接口**；模板用 Jinja2，变量缺失要报错。
5. **S3-5 问答 API + 会话落库**：`conversations`/`messages`/`message_citations` 只在 `SCHEMA.md §7`，**尚无 model/migration**；`POST /qa/ask` 用 SSE，先落 user 消息，结束落 assistant + citations，客户端断开要中断上游。
6. **S3-6 拒答与引用校验**：在 `answer_question` 外做引用编号校验，最多重试一次；仍失败加“模型补充”前缀。
7. **S3-7 缓存/日志/用量**：`llm_call_logs` 在 `SCHEMA.md §8.4`，尚无 model/migration；Redis 缓存 + `/admin/usage`；单价配置化。
8. **S3-8 前端问答页**：当前 `/qa` 仍是 `ComingSoonView`；需 `views/qa/Chat.vue`、流式渲染、Markdown/KaTeX、引用卡片跳转高亮、会话列表。
9. **S3-9 线上评测**：扩到约 40 条，三种配置真实数字写入 `docs/EVAL_M2.md`；完成后打 `m2-rag-done`。

## 5. 关键风险（提前记住）

- `POST /qa/ask` 是 POST + SSE，浏览器端不能用原生 `EventSource`，用 `fetch` 读流；Nginx 必须 `proxy_buffering off`，提前写进 `deploy/README.md`。
- 引用跳转是答辩亮点：优先按 `note_id + chunk` 定位，前端高亮/滚动要做扎实。
- 不要编造评测数字；三种配置必须真实跑出并留结果文件。
- 新表一律先改 `docs/SCHEMA.md` / `docs/API.md`，再写 model/migration；接口变更先改契约。
- 迁移只增不改历史；当前迁移到 `0005_s2_8_parse_progress.py`。
- 教师/家长不是学生数据所有者；不要用放宽 `require_role("student")` 的方式图省事。

## 6. 新会话开场建议

1. 读 `AGENTS.md` §10、本页、`docs/PROGRESS.md`、`docs/API.md §5`、`docs/SCHEMA.md §7/§8.3/§8.4`。
2. 先做 S3-1 的 brainstorming + spec，不要直接改代码；spec/plan 经用户确认后再实现。
3. 每个任务完成：跑后端 pytest + 前端 Vitest/build、真实接口或浏览器验收、更新 `API.md`/`SCHEMA.md`/`DECISIONS.md`/`PROGRESS.md`、Conventional Commit；`git push` 由用户执行。
