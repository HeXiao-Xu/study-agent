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

## 快速开始

### 首次准备（只做一次）

- Python venv：`py -3.11 -m venv .venv`，然后 `.venv\Scripts\Activate.ps1`，再
  `pip install -i https://repo.huaweicloud.com/repository/pypi/simple -r backend/requirements.txt`
- 前端依赖：`cd web` → `npm install`（项目已配 npmmirror 国内源）
- 复制 `.env.example` 为 `.env`（默认开发值即可用）
- 安装并打开 Docker Desktop（等左下角 **Engine running**）

### 日常启动（每次开机后，按需三个终端）

```powershell
# ① 基础服务（数据库/缓存/文件存储）——先开 Docker Desktop 等引擎变绿
cd E:\BiShe-AIStudy\study-agent
docker compose -f deploy/docker-compose.dev.yml up -d
python scripts\check_services.py        # 应输出 3/3 通过

# ② 后端（新开一个终端）
cd E:\BiShe-AIStudy\study-agent\backend
uvicorn app.main:app --reload           # 看到 "Application startup complete" 即成功
# 交互式 API 文档：http://127.0.0.1:8000/docs

# ③ 前端（再开一个终端）
cd E:\BiShe-AIStudy\study-agent\web
npm run dev                             # 看到 "Local: http://localhost:5173/" 即成功
# 验收页：http://localhost:5173/debug（显示后端 /health 结果）
```

> `uvicorn` / `python` 都来自 `.venv`：PyCharm 终端会自动激活（行首有 `(.venv)` 前缀）；
> 普通 PowerShell 先跑 `.venv\Scripts\Activate.ps1` 再用。
> 弹性开关：只改前端样式可不起后端；只做不连库的后端活可不起 Docker（/health 不连库）。

### 收工

- 后端、前端终端各按一次 `Ctrl+C`
- 三件套：`docker compose -f deploy/docker-compose.dev.yml stop`（数据在命名卷，不会丢）

### 环境自检（S0-7 交付）

```powershell
python scripts\smoke.py    # 一条命令查三件套/扩展/桶/后端/前端；全 PASS = 环境就绪
```

## 常见问题（Windows 特有）

| 症状 | 原因与解法 |
|---|---|
| PowerShell 报「无法加载 npm.ps1 …未进行数字签名」 | 执行策略挡了脚本，一次性修复：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`（顺带解锁 `.venv` 激活脚本） |
| 端口被占（5432/6379/9000/9001/8000/5173） | `netstat -ano \| findstr :8000` 找 PID → 任务管理器结束进程，或 `taskkill /PID <pid> /T /F`。注意：uvicorn `--reload` 杀主进程会留**孤儿子进程**继续占端口，必须按 PID 一并结束 |
| `docker compose up` 报 `bind: address already in use` | 同上查占用；或改 `.env` 里对应 `*_PORT` 换端口 |
| Docker Desktop 引擎起不来 / 提示 WSL2 更新 | 按提示装 WSL2 更新（一般要重启电脑一次）；仍不行：设置 → Troubleshoot → Restart |
| 拉镜像极慢或超时 | Docker Hub 直连慢，用华为云镜像前缀拉取再重标记（见 [deploy/README.md](deploy/README.md)「镜像加速」） |
| PyCharm 终端行首没有 `(.venv)`，`uvicorn`/`python` 报找不到 | 先跑 `.venv\Scripts\Activate.ps1`；并检查设置里解释器指向本项目 venv |
| `ModuleNotFoundError: No module named 'fastapi'` | venv 没激活就装了依赖，或根本没装：激活后 `pip install -r backend/requirements.txt` |
| git 提示 `LF will be replaced by CRLF` | 换行符警告，无害，忽略 |
| docling 首次解析卡住或超时（模型下载） | HuggingFace 直连不通，且镜像后还有 Xet 块存储坑：先设 `$env:HF_ENDPOINT='https://hf-mirror.com'; $env:HF_HUB_DISABLE_XET='1'`（**两个都要**）再跑；模型 342MB 只下载一次，之后离线可用（已缓存本机） |

## 开发必读（仓库的"记忆系统"，AI 协作开发的规矩）

| 文件 | 作用 |
|---|---|
| [AGENTS.md](AGENTS.md) | 项目宪法：技术栈、目录约定、编码规范、禁止事项 |
| [docs/SCHEMA.md](docs/SCHEMA.md) | 数据模型契约（建表与迁移的唯一依据） |
| [docs/API.md](docs/API.md) | 接口契约（前后端的共同语言） |
| [docs/PROGRESS.md](docs/PROGRESS.md) | 进度看板与遗留问题 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术决策记录（论文选型章节的草稿） |

## 当前进度

阶段 0（项目启动）**已完成**，里程碑 `m0-env-ready`；阶段 1（RAG 技术验证）进行中：S1-1 文档解析已完成。
详见 [docs/PROGRESS.md](docs/PROGRESS.md)。
