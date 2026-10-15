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
