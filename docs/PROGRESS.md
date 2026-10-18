# 项目进度

> 更新规则：每个任务完成后由 AI 更新本文件（AGENTS.md §7）；周末对照打卡表复盘。
> 总表来源：docs/AI协作开发实施计划.md 第 14 章。★ 标记为关键路径任务（做不好整项目就废，必须亲自验收）。

## 当前状态

- 阶段：阶段 1（RAG 技术验证，M0）——阶段 0 已完成（tag `m0-env-ready`）
- 最近完成：S1-2 结构化切片器（两阶段管道 + 题号检测 + 300-600/800 尺寸规则 + 60-token 重叠；pytest 44/44）
- 下一步：S1-3 Embedding 与 pgvector 入库
- 已知阻塞：无

## 任务清单

### 阶段 0：项目启动
- [x] S0-1 仓库与工程骨架
- [x] S0-2 AGENTS.md 项目宪法
- [x] S0-3 SCHEMA.md + API.md 契约文档
- [x] S0-4 Postgres/Redis/MinIO 基础服务
- [x] S0-5 后端最小可运行（配置/日志/异常/health）
- [x] S0-6 前端最小可运行（路由/http 封装）
- [x] S0-7 冒烟脚本 + README

### 阶段 1：RAG 技术验证（M0）
- [x] S1-1 文档解析为结构化文本
- [x] S1-2 结构化切片器 ★
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
- S0-6 完成：web/ 前端工程（官方 create-vite vue-ts 模板：Vue 3.5.42 + Vite 8.3.0 + TS 6.0.2，package-lock 锁版本；web/.npmrc 走 npmmirror 国内源）。新增 element-plus（全局注册，按任务卡）/ pinia / vue-router / axios（均为 AGENTS 技术栈点名，无新依赖）。src/api/http.ts（baseURL 取 VITE_API_BASE、请求拦截注入 Bearer token、响应拦截统一错误提示与 401 跳 /login 占位）；src/stores/auth.ts（token + localStorage 持久化）；src/router/index.ts（/ 重定向 /debug，视图懒加载）；src/views/DebugView.vue（调 GET /health 展示统一壳）。跨域走后端 CORS、vite 刻意不配 proxy（任务卡坑：二选一）。web/.env.development/.env.production/.env.example 三件套，根 .gitignore 放行前端 env 文件（非机密）。环境修复：PowerShell 执行策略 CurrentUser=RemoteSigned（此前 npm.ps1 与 Activate.ps1 均被挡）。插曲：清理了 8000 端口上 --reload 模式的孤儿子进程（multiprocessing spawn，父进程已被误杀）。验收：npm run build 通过（vue-tsc 零类型错误；TS 6.0 弃用 baseUrl，paths 改为显式 ./ 相对写法；主 chunk 1MB/gzip 327KB 为 Element Plus 全局注册的已知代价）；CORS 实测响应头回 access-control-allow-origin: http://localhost:5173；用户浏览器打开 /debug 人工验收通过。收尾：前后端 dev 服务与 Docker 三件套已全部停止（端口清零），日常启动手册写入 README 快速开始
- S0-7 完成：scripts/smoke.py（8 项检查：三件套连通[复用 check_services 不重复实现] / pgvector 扩展[docker exec psql，零数据库驱动依赖] / bucket[HTTP 403/404 匿名探测] / 后端 /health[校验统一壳语义，严于 curl] / 业务表[当前阶段无表属预期不判失败，REQUIRED_TABLES 清单 S2-1 起随迁移维护] / 前端 dev[可选组件，未启动记 SKIP 不判失败]；彩色清单、FAIL 附修复提示、失败退出码 1、自动读根 .env、Windows 旧控制台激活 ANSI）。README 新增「常见问题（Windows 特有）」8 条（全部为本机真实踩过的坑：执行策略/端口占用含 --reload 孤儿进程/WSL2/镜像加速/venv 激活/依赖丢失）并更新当前进度为阶段 0 完成。修复：前端探测 URL 必须用 localhost 主机名——vite/Node17+ 绑 IPv6 ::1（实测监听地址 ::1:5173），硬写 127.0.0.1 会误报未启动。验收：正向 8/8 全 PASS 退出码 0；反向（停后端）[6/8] FAIL 带原因与启动提示、退出码 1。里程碑：git tag m0-env-ready（阶段 0 收官）
- 关联 GitHub 远程仓库 https://github.com/HeXiao-Xu/study-agent.git（origin）；期间发现 .git 曾意外丢失（当时尚无任何提交，零损失），已重新 git init（main 分支）
- 附录 F 拍板落定（4 项，2026-10-15）：#3 仅本地部署（D-009，低于方案建议的「本地+局域网」档位）；#4 Agent 选做、M5 后（D-010，降级预案提前约定）；#5 自测偶尔使用（D-011——验证策略主体由「自用数据」转为 eval/ 评测集，评测建设升为关键路径）；#7 学校允许 AI 辅助编码、无附加要求（D-012，原「M0 前确认」阻塞解除）
- AGENTS.md 扩充 §9 功能编码细则（含 §9.6 一致性锚点机制）与 §10 任务执行协议（spec→plan 双确认流程，功能卡一律全流程）；docs/{spec,plan}/ 目录约定入 §3

### 2026-10-18
- S1-1 完成（按 §10 全流程：spec docs/spec/s1-1-doc-parse.md + plan docs/plan/s1-1-doc-parse.md，均经用户确认后实施）。交付：backend/app/ai/parse/ 六件套（__init__ 门面集中降级决策 / models 统一结构 ParsedBlock/ParsedDocument / base 可替换契约 DocumentParser / pdf_docling 结构化映射 / pdf_pymupdf 兜底+is_scanned 采样+控制符清洗 / docx_parser 中英文 Heading 样式与表格转 Markdown）；scripts/parse_demo.py（CLI：--limit / --force-pymupdf）；Settings + .env(.example) 增 PARSE_FORCE_PYMUPDF；requirements 钉版 docling 2.140.0 / pymupdf 1.28.2 / python-docx 1.2.0；parse/ 目录 .gitkeep 已删
- 验收证据：pytest 20/20（含 docling mock 影射、降级链、扫描版提前返回、中英 Heading、表格成块、控制符清洗）；三份真实样张（笔记/试卷/教材页）程序化核对 37 项断言 36 过——唯一失败项（教材页 ⊆ 丢失）经 docling 与 PyMuPDF 双提取器交叉验证证明为样张 PDF 自身 ToUnicode 缺陷（reportlab+宋体把 ⊆ 写成 \x00），非解析器问题，已记 D-013 已知观察②；试卷 2 页页码正确分流，教材页页眉页脚被 docling 正确滤除（PyMuPDF 兜底路径漏入，对比鲜明）
- 网络坑与解法（已记 README FAQ 与 spec §9）：docling 模型下载 HF 直连超时 → hf-mirror 镜像又撞 Xet 块存储 401 → 需同时设 HF_ENDPOINT=https://hf-mirror.com 与 HF_HUB_DISABLE_XET=1；模型 342MB 已缓存本机离线可用；首跑 466.2s；安装约 15 分钟（华为云源），site-packages 总量 1404MB
- 已知观察（S1-2 消化，见 D-013）：docling 结构模型对平级标题可能判成嵌套（笔记样张「二/三」挂「一」下）；heading_path 在切片器中定位为上下文链而非严格层级
- 文档同步：DECISIONS D-013、AGENTS §9.6 ai 适配器锚点回填（pdf_docling.py）、spec §9 实测数字回填、README FAQ +docling 模型下载行、当前进度更新

### 2026-10-19
- S1-2 完成（按 §10 全流程：spec docs/spec/s1-2-chunker.md + plan docs/plan/s1-2-chunker.md，均经用户确认后实施）。交付：backend/app/ai/rag/chunker.py（Chunk/ChunkType 模型；两阶段管道 _build_units「题号吞并选项/大题标题边界/标题前置并入/表格公式不可切」+ _split_unit「300-800 尺寸切分、笔记 60-token 尾部重叠、题目无重叠」；门面 chunk_document；tiktoken cl100k_base 计数收敛单点）；backend/tests/test_chunker.py（24 条用例覆盖 5 规则+边界）；scripts/chunk_demo.py（解析→切片→逐块摘要 + ASCII token 直方图）；SCHEMA.md note_chunks 加 chunk_type 列（契约先行）；requirements +tiktoken==0.14.0；rag/ 目录 .gitkeep 已删
- 验收证据：pytest 44/44（S1-1 20 + S1-2 24）；三份真实样张——试卷 23 块（question 17 = 17 题一题一块，题干+选项+小问聚齐；答题线已剔除）、笔记 6 块（含纯公式行正确标 formula；层级链完整）、教材页 9 块（例1/例2/练习题分别成块）；token 直方图主体 0–300、无 >800 块；用户亲眼验收通过
- 实测抓修 5 个真问题（记录于 D-015 决策 4/5）：①纯数值选项行被 formula 密度规则截胡导致第 2 题丢选项 → 选项行豁免 ②纯答题线 `________` 假命中 formula 拆碎解答题 → 预处理丢弃 ③小问行 `（1）f(x)=…` 同类截胡 → 小问行豁免 ④教材章节号「3.2.1」被当题号 → 题号正则加数字排他 `(?!\d)` ⑤演示直方图末桶标签 bug（>1000000000 → >800）
- 已知观察（不修）：docling 把「三、解答题（本题共 5 小题，共 90」折成两块且第二条误嵌套成标题层——D-013 已知现象延伸，解析器行为不在本卡范围
- 文档同步：DECISIONS D-015、spec §4.5/§4.6 豁免与边界回填、spec §4.1 章节号保护、spec §7 tiktoken 实测回填、PROGRESS
