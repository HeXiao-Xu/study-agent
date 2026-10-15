# 项目进度

> 更新规则：每个任务完成后由 AI 更新本文件（AGENTS.md §7）；周末对照打卡表复盘。
> 总表来源：docs/AI协作开发实施计划.md 第 14 章。★ 标记为关键路径任务（做不好整项目就废，必须亲自验收）。

## 当前状态

- 阶段：阶段 0（项目启动）
- 最近完成：S0-5 后端最小可运行（/health 200 统一壳、404 错误壳、X-Trace-Id 透出、pytest 3/3）
- 下一步：S0-6 前端最小可运行（路由/http 封装）
- 已知阻塞：
  1. 方案附录 F 的待拍板项尚未与导师确认，尤其「学校对 AI 辅助编码的要求」（M0 前确认）

## 任务清单

### 阶段 0：项目启动
- [x] S0-1 仓库与工程骨架
- [x] S0-2 AGENTS.md 项目宪法
- [x] S0-3 SCHEMA.md + API.md 契约文档
- [x] S0-4 Postgres/Redis/MinIO 基础服务
- [x] S0-5 后端最小可运行（配置/日志/异常/health）
- [ ] S0-6 前端最小可运行（路由/http 封装）
- [ ] S0-7 冒烟脚本 + README

### 阶段 1：RAG 技术验证（M0）
- [ ] S1-1 文档解析为结构化文本
- [ ] S1-2 结构化切片器 ★
- [ ] S1-3 Embedding 与 pgvector 入库
- [ ] S1-4 混合检索 + RRF ★
- [ ] S1-5 Rerank 接入
- [ ] S1-6 带引用回答 + 拒答 ★
- [ ] S1-7 自测用例与效果抽查 20–30 条 ★

### 阶段 2：基础框架（M1）
- [ ] S2-1 数据模型与迁移（第一批）
- [ ] S2-2 认证 JWT
- [ ] S2-3 RBAC 与数据隔离
- [ ] S2-4 通用分页/排序/筛选
- [ ] S2-5 笔记表与 CRUD API
- [ ] S2-6 文件上传 + MinIO + 去重
- [ ] S2-7 异步任务框架
- [ ] S2-8 文档解析 Worker
- [ ] S2-9 知识点树 CRUD + 导入
- [ ] S2-10 知识点对齐与待确认队列
- [ ] S2-11 前端登录/布局/路由守卫
- [ ] S2-12 前端笔记列表与编辑器
- [ ] S2-13 前端上传与解析状态
- [ ] S2-14 前端知识点树管理

### 阶段 3：RAG 问答上线（M2）
- [ ] S3-1 索引服务产品化
- [ ] S3-2 检索服务
- [ ] S3-3 Query 改写与意图识别
- [ ] S3-4 上下文组装 + Prompt 版本管理
- [ ] S3-5 问答 API（SSE）+ 会话落库
- [ ] S3-6 拒答与引用校验
- [ ] S3-7 缓存 + 调用日志 + 用量统计
- [ ] S3-8 前端问答页（流式 + 引用跳转）★
- [ ] S3-9 抽查扩展到线上链路 + 三种配置对照

### 阶段 4：错题与知识图谱（M3）
- [ ] S4-1 题库表 + 试卷切题
- [ ] S4-2 错题录入 + 状态机
- [ ] S4-3 错因诊断服务 ★
- [ ] S4-4 变式题生成 + 复算自检
- [ ] S4-5 图谱关系构建 + 人工校验
- [ ] S4-6 图谱可视化前端
- [ ] S4-7 掌握度模型 ★
- [ ] S4-8 错题统计看板

### 阶段 5：练习与复习（M4）
- [ ] S5-1 组卷算法 + 单测 ★
- [ ] S5-2 组卷 API + 预览页
- [ ] S5-3 PDF 导出
- [ ] S5-4 在线作答与掌握度回写
- [ ] S5-5 复习调度 + 每日清单
- [ ] S5-6 学习报告 + 周报
- [ ] S5-7 前端复习/报告/练习页

### 阶段 6：Agent（M5）
- [ ] S6-1 工具集实现 + 单测
- [ ] S6-2 LangGraph 状态机 + 步骤持久化 ★
- [ ] S6-3 任务 A：周笔记整理 + 思维导图
- [ ] S6-4 任务 B：错题组卷（人工确认）
- [ ] S6-5 前端任务进度页
- [ ] S6-6 可靠性加固

### 阶段 7：调优上线（M6–M7）
- [ ] S7-1 自测抽查与参数调优
- [ ] S7-2 性能压测与优化
- [ ] S7-3 部署上线 + 备份
- [ ] S7-4 自用试用与问题迭代
- [ ] S7-5 论文图表数据导出
- [ ] S7-6 演示环境与录屏

## 遗留问题（TECH DEBT）

| # | 问题 | 影响 | 计划处理时间 |
|---|---|---|---|
| 1 | SCHEMA.md 中 ⚠ 标记的推断类型/索引未复核 | 建表返工 | S2-1 建迁移前 |
| 2 | API.md 存在 TODO 待定字段与待定接口 | 前后端并行开发受限 | 各对应任务定稿时 |
| 3 | 方案附录 F 待与导师拍板项未确认 | 决策悬空 | M0 里程碑前 |

## 变更日志

### 2026-10-15
- S0-1 完成：monorepo 骨架（backend/web/docs/deploy/scripts/eval，含 backend/app 分层与 eval 子目录）；.gitignore；README.md；删除 PyCharm 欢迎脚本 main.py / test_main.http；.idea 移出版本控制
- S0-2 完成：AGENTS.md（实施计划附录 A 模板 + 文档引用）；《完整方案》《实施计划》入库 docs/
- S0-3 完成：docs/SCHEMA.md（方案第 5 章整理，25 张表 + 枚举 + 索引策略）；docs/API.md（第 6 章 + 附录 B 整理，22 条接口 + 待定清单）；初始化 docs/PROGRESS.md、docs/DECISIONS.md
- 提交建议：三个 commit（见会话记录 / 遵循 Conventional Commits）
- Python 版本拍板：确定沿用 3.14（DECISIONS.md D-006，含风险与回退方案）；AGENTS.md、README.md 已同步，现有 .venv 无需重建
- Python 版本改回 3.11：已安装 3.11.9（DECISIONS.md D-007 取代 D-006，官方安装包经华为云镜像下载）；AGENTS.md、README.md 已同步回 3.11；项目 .venv 待用 3.11.9 重建
- venv 重建完成：`.venv` 已是 3.11.9（pyvenv.cfg 验证：home=Python311），D-007 已补记验证结果
- S0-4（基础服务）用户决定暂时跳过，顺延执行；随后改变决定，恢复执行
- S0-4 前置环境检查：Docker 27.5.1 + Compose v2.32.4 已安装；端口 5432/6379/9000/9001 空闲；磁盘充足（C 113GB / E 224GB）；Docker 引擎未启动，待用户启动 Docker Desktop 后开始
- 首次推送完成：main 已同步至 origin（GitHub）
- S0-4 完成：deploy/docker-compose.dev.yml（pgvector:pg16 + redis:7-alpine + minio + mc 自动建桶，命名卷持久化，端口仅绑 127.0.0.1）；deploy/initdb/01-extensions.sql（首启自动 CREATE EXTENSION vector）；scripts/check_services.py（仅标准库）；deploy/README.md；.env.example。验收证据：check_services 3/3 通过（postgres 协议握手 / redis PING/PONG / minio health 200），pg_extension 含 vector，bucket study-agent 创建成功，postgres 与 redis healthcheck healthy。镜像来源：复用本机已有 pgvector/minio 镜像重标记，mc 经华为云 SWR 镜像拉取（Docker Hub 直连约 110KB/s、DaoCloud 502，经验已记入 deploy/README.md）
- S0-5 完成：backend 首批代码——app/main.py（应用工厂 + CORS + TraceId 中间件 + /health）、core/{config,logging,exceptions,context,middleware}.py、schemas/common.py（统一响应壳 Envelope[T]）、tests/test_main.py。requirements.txt 固定版本（fastapi 0.143.1 / uvicorn 0.54.0 / pydantic 2.14.1 / pydantic-settings 2.16.0 / pytest 9.1.1 / httpx 0.28.1，华为云镜像安装；pytest+httpx 为用户确认的新增依赖，D-008）。验收实跑：GET /health → 200 统一壳；未知路由 → 404 {code:40400, message, trace_id, data:null}；X-Trace-Id 响应头必返且支持请求头续链（trace-demo-999 实测回显）；pytest 3 passed。错误码表与 trace_id 透出格式定稿至 docs/API.md §0/§13；.env.example/.env 新增 APP_NAME/ENV/LOG_LEVEL/CORS_ORIGINS/MINIO_ENDPOINT
- 关联 GitHub 远程仓库 https://github.com/HeXiao-Xu/study-agent.git（origin）；期间发现 .git 曾意外丢失（当时尚无任何提交，零损失），已重新 git init（main 分支）
