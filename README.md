# 个性化学习智能体（study-agent）

> 面向高中生的个性化复习系统：把「笔记 + 错题 + 试卷 + 教材考纲」变成结构化知识资产——
> RAG 可溯源问答、错题诊断、掌握度驱动的组卷与复习计划、Agent 多步任务。

毕业设计项目。完整设计见 [docs/个性化学习智能体-毕业设计完整方案.md](docs/个性化学习智能体-毕业设计完整方案.md)，
分阶段任务卡（S0-1 ~ S7-6）见 [docs/AI协作开发实施计划.md](docs/AI协作开发实施计划.md)。

## 核心能力

1. **多模态笔记管理**：文字 / 图片 / PDF / 拍照试卷录入，公式与题目结构化，按知识点自动归档
2. **AI 知识点抽取与知识图谱**：从笔记与试卷中抽取知识点，对齐标准知识点树，构建"前置-相关-易混淆"关系
3. **AI 错题分析**：错因定位（知识点 + 错因类型 + 第一处错误步骤）、同类变式题生成、关联笔记与前置知识
4. **个人笔记知识库 RAG 问答**：混合检索 + 重排 + 引用溯源，答案能点回原文位置；检索不到就明确拒答
5. **试题生成与自适应组卷**：按知识点覆盖度、难度分布、题型配比自动组卷，可导出 PDF 打印
6. **个性化复习计划**：掌握度模型 + 遗忘曲线调度，输出"今日复习清单"与学习报告/思维导图

## 技术栈

`Vue3 + TS + Element Plus` ｜ `FastAPI + SQLAlchemy2 + Alembic` ｜ `PostgreSQL16 + pgvector` ｜
`Redis + ARQ + APScheduler` ｜ `MinIO` ｜ `DeepSeek-V3(对话) + 厂商 Embedding/Rerank API` ｜
`Docling(文档解析) + 多模态 API(图片试卷) + jieba(分词) + Playwright(PDF导出)` ｜ `LangGraph(Agent)` ｜ `Docker Compose + Nginx`

## 目录结构

| 目录 | 说明 |
|---|---|
| `backend/` | FastAPI 后端，`app/` 下按 api / models / schemas / services / ai / core / tasks / utils 分层 |
| `web/` | Vue3 前端（S0-6 用 Vite 初始化） |
| `docs/` | 仓库记忆与契约文档：SCHEMA / API / PROGRESS / DECISIONS + 方案文档 |
| `deploy/` | Docker Compose 等部署配置（S0-4 交付） |
| `scripts/` | 自测、冒烟、命令行验证脚本（阶段 1 RAG 验证的主战场） |
| `eval/` | 评测数据集、配置与结果（论文数字的来源，须真实实测） |

## 环境要求

- **Python 3.11.9**（方案锁定 3.11；已安装于本机 `...\Programs\Python\Python311`，决策记录见 [docs/DECISIONS.md](docs/DECISIONS.md) D-007）
- Node.js 18+（S0-6 起）
- Docker Desktop（Postgres 16 + pgvector / Redis / MinIO，S0-4 起）

## 快速开始（随 S0-4 ~ S0-7 逐步补全）

```bash
# 1. 基础服务（S0-4 交付）
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. 后端（S0-5 交付）
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. 前端（S0-6 交付）
cd web
npm install
npm run dev

# 4. 环境自检（S0-7 交付）
python scripts/smoke.py
```

## 开发必读（仓库的"记忆系统"，AI 协作开发的规矩）

| 文件 | 作用 |
|---|---|
| [AGENTS.md](AGENTS.md) | 项目宪法：技术栈、目录约定、编码规范、禁止事项 |
| [docs/SCHEMA.md](docs/SCHEMA.md) | 数据模型契约（建表与迁移的唯一依据） |
| [docs/API.md](docs/API.md) | 接口契约（前后端的共同语言） |
| [docs/PROGRESS.md](docs/PROGRESS.md) | 进度看板与遗留问题 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术决策记录（论文选型章节的草稿） |

## 当前进度

阶段 0（项目启动）进行中，详见 [docs/PROGRESS.md](docs/PROGRESS.md)。
