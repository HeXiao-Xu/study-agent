# AGENTS.md — 项目开发约束（AI 助手必读）

## 1. 项目一句话
面向高中生的个性化复习系统：个人知识库可溯源问答（RAG）+ 错题诊断 + 掌握度驱动的组卷与复习计划 + Agent 多步任务。

## 2. 技术栈（不要擅自更换）
- 后端：Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2
- 前端：Vue 3 + TypeScript + Vite + Pinia + Element Plus + ECharts + md-editor-v3 + KaTeX
- 数据：PostgreSQL 16 + pgvector（关系/向量/全文同库）、Redis（缓存+队列）、MinIO（文件）
- 异步：ARQ（队列）+ APScheduler（定时）
- 文档解析：Docling 或 Marker（PyMuPDF 兜底）；中文分词：jieba
- AI：LLM 走 OpenAI 兼容接口（DeepSeek/Qwen 可切换）；
      Embedding 与 Rerank 走厂商 API；不要引入本地模型依赖（sentence-transformers / FlagEmbedding / PaddleOCR）
- 认证：fastapi-users（或 FastAPI 官方安全示例）；分页：fastapi-pagination；模板：Jinja2
- 结构化输出：instructor（或 Pydantic + 重试）；PDF 导出：Playwright（不要用 WeasyPrint）
- Agent：LangGraph
- 部署：Docker Compose + Nginx

## 2.1 依赖与复用原则
- 新需求先找成熟库/API；只有论文创新点那 9 块自己实现
- 擅自引入新依赖前必须先说明理由并等确认
- 不引入需要本地下载大模型的依赖（除非明确要求）
- 任何"手写通用能力"（分词、分页、认证、定时、PDF 渲染、JSON 修复）都要先确认有没有现成库

## 3. 目录约定
backend/app/{api,models,schemas,services,ai,core,tasks,utils}
backend/app/ai/{llm,embedding,rerank,rag,parse,ocr,prompts,agents}
web/src/{api,components,views,stores,router,utils,types}
docs/{PROGRESS.md,API.md,SCHEMA.md,DECISIONS.md}
docs/{spec,plan}/    # 功能设计 spec 与实现 plan（流程见 §10）
eval/{datasets,configs,results}

## 4. 编码规范
- 分层：路由只做参数校验与调用；业务逻辑在 services；AI 调用只在 ai/ 层
- 命名：数据库与 API 用 snake_case；前端变量用 camelCase；常量全大写
- 类型：所有函数签名必须有类型标注；Pydantic 模型用于所有出入参
- 异步：IO 密集用 async；CPU 密集（embedding/rerank）走线程池或独立 worker
- 错误：不吞异常，不用 `except: pass`；异常带上下文与 trace_id
- 数据库：所有查询必须显式过滤 user_id（除非是公共语料）；禁止在循环里查库
- 注释：只解释"为什么"，不复述"做了什么"

## 5. AI 调用约束
- 所有 LLM/Embedding/Rerank 调用必须走 ai/ 层的 Client 适配器，禁止在业务代码里直接调 SDK
- 每次调用必须记录：scene、model、tokens、cost、latency、trace_id → llm_call_logs
- 结构化输出必须用 Pydantic 校验 + 失败重试（最多 2 次）
- Prompt 必须存放在 prompts/ 目录或 prompt_templates 表，禁止硬编码长 Prompt
- API Key 只能从环境变量读，禁止出现在代码、日志、提交历史中

## 6. 禁止事项
- 禁止修改已提交的 Alembic 迁移文件
- 禁止引入未经确认的新依赖
- 禁止在任务范围外"顺手重构"其他模块
- 禁止删除或跳过已有测试来让测试通过
- 禁止生成假的自测数据、假的抽查结果；所有数字必须来自本人实测
- 禁止把真实学生的姓名、学校、联系方式写入日志或示例数据

## 7. 验收习惯（每个任务必须做到）
1) 改完代码给出可执行的验证命令（pytest / curl / 界面路径）
2) 新增功能必须配测试，外部 LLM 调用必须 mock
3) 更新 docs/PROGRESS.md；接口变化同步 docs/API.md
4) 新增环境变量同步 .env.example；新增依赖同步 requirements.txt / package.json
5) 生成符合 Conventional Commits 的提交信息

## 8. 与其他文档的关系
- docs/SCHEMA.md：数据结构的唯一依据，冲突时以它为准
- docs/API.md：接口契约的唯一依据，前后端都以它为准
- docs/PROGRESS.md：当前进度与遗留问题的唯一依据
- 项目方案见 docs/个性化学习智能体-毕业设计完整方案.md
- 实施步骤与任务卡见 docs/AI协作开发实施计划.md（任务编号 S0-1 ~ S7-6 均出自该文件）
- 若发现文档与代码不一致，先报告，不要自行决定改哪边。

## 9. 功能编码细则（S1 起写正式功能代码时逐条自检）

### 9.1 动笔前
- 先读任务卡与对应契约（接口→docs/API.md，数据→docs/SCHEMA.md）；发现契约冲突停下报告（§8），不自行裁决
- 契约先行：新接口先补 API.md、新表先补 SCHEMA.md，再写代码
- 新代码先对「一致性锚点」（§9.6）找样，再动手
- 功能实现走 §10 的 spec→plan 流程

### 9.2 后端（FastAPI + Pydantic v2 + SQLAlchemy 2.0）
- 路由函数 ≤30 行是常态：参数校验 → service 调用 → 统一壳组装；超了说明该挪 service
- 出入参一律 Pydantic 模型（schemas/）；路由与 service 之间禁止传裸 dict
- service 一个用例一个事务；失败回滚后抛带上下文异常，禁止吞异常返回 None
- 时间统一 UTC 存储、ISO-8601 输出；分数/金额用整数存储，不用 float（浮点误差）
- 业务错误一律抛 AppError 子类（S0-5 体系），禁止路由里手拼错误 JSON 或裸 HTTPException
- 配置只从 core/config.py 的 Settings 读；其他模块禁止直读 os.environ
- 外部 HTTP 调用超时必设、失败必处理

### 9.3 AI 层（阶段 1 的高压线）
- ai/ 之外禁止 import openai/httpx 客户端；业务层只 import ai/ 的适配器
- 每次调用落 llm_call_logs：scene/model/tokens/cost/latency/trace_id
- 结构化输出：Pydantic 校验 + 最多 2 次重试；仍失败抛专用异常，禁止返回半解析结果
- 代码里禁止出现超过 3 行的 prompt 字符串（存 ai/prompts/ 或 prompt_templates 表）
- 适配器可替换：Docling/PyMuPDF、DeepSeek/Qwen、Embedding 厂商都要能配置切换

### 9.4 测试
- 命名：tests/test_<模块>.py，用例 test_<被测函数>_<场景>_<预期>
- LLM/网络等外部依赖一律 mock（喂固定 JSON）；测试套件禁止任何真实外部调用
- service 公共函数至少 2 条用例：1 条 happy path + 1 条失败路径（权限/不存在/非法输入择一）
- 测试数据"明显假、结构真"（如"测试用户_1"，字段类型符合 SCHEMA.md）
- pytest 全绿是提交前提；确需跳过用例必须写明原因并经用户确认

### 9.5 前端（阶段 2 起）
- API 调用只经 src/api/ 封装（S0-6 http.ts 模式）；组件里禁止直接 import axios
- http.ts 已统一弹错，组件只写"成功渲染 + 局部状态"，不重复 try-catch 弹窗
- 跨组件状态进 Pinia；props 单向数据流
- 前端校验规则与后端 Pydantic 保持一致（从 API.md 抄，不各自发明）

### 9.6 一致性锚点（每个正式模块落地后回填，防代码风格漂移）
- 后端路由样例：（待 S2 首个正式路由后回填）
- ai 适配器样例：backend/app/ai/parse/pdf_docling.py（可替换适配器，duck-typing 便于 mock；契约见同目录 base.py，统一出入参 models.py，门面 __init__.py 集中降级决策）
- ai Embedding 适配器样例：backend/app/ai/embedding/openai_compat.py（同一抽象 base.py；门面 __init__.py 按配置切换厂商；本地实现 local.py 仅占位）
- RAG 检索器样例：backend/app/ai/rag/retriever.py（向量 + 全文 + RRF；user_id 过滤下推；RRF 纯函数只认排名）
- 规则：写新代码先照锚点文件的样式；觉得锚点过时 → 先提出来改锚点，再写新码

## 10. 任务执行协议（功能先 spec 后 plan，再写码）
1. 读任务卡 + 契约 → 走 superpowers 流程：brainstorming 澄清需求与设计 → **spec** 落 `docs/spec/<任务号>-<主题>.md`（如 s1-1-doc-parse.md）；writing-plans → **plan** 落 `docs/plan/<任务号>-<主题>.md`（分步、每步带验证命令）；spec 与 plan 都经用户确认后才写码
2. 严格按 plan 实现；要偏离 plan 必须先说明原因并获用户同意
3. 规模适配（避免仪式拖垮小活）：小修/bugfix 不开 spec/plan，聊天里短设计 + 确认即可；功能级任务卡一律全流程
4. 写完 → 真实验证（pytest/curl/界面路径）→ 贴实测输出，禁止"应该没问题"
5. 文档同步：PROGRESS 必更；动接口补 API.md、动表补 SCHEMA.md、动配置补 .env.example、动依赖补 requirements/package.json
6. Conventional Commits 提交（含任务号，如 feat(s1-2)）；用户负责 git push
7. 验收不过或做不完：如实报告，禁止粉饰进度、禁止假数据（§6）
8. spec/plan 与 API.md/SCHEMA.md 冲突时契约文档优先；发现不一致先报告（§8）
