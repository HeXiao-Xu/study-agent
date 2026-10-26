# 项目进度

> 更新规则：每个任务完成后由 AI 更新本文件（AGENTS.md §7）；周末对照打卡表复盘。
> 总表来源：docs/AI协作开发实施计划.md 第 14 章。★ 标记为关键路径任务（做不好整项目就废，必须亲自验收）。

## 当前状态

- 阶段：阶段 2（基础框架，M1）——阶段 0/1 已完成（tag `m0-env-ready` / `m0-rag-validated`）
- 最近完成：S2-5 笔记表与 CRUD API（迁移 0003 建 files/notes/note_kps + note_chunks 外键；5 个笔记接口；`content_text` 派生；pytest 322/322，curl + psql 实测）
- 下一步：S2-6 文件上传 + MinIO + sha256 去重（依赖本卡建好的 `files` 表与 `uq_files_user_sha256`）
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
- [x] S1-3 Embedding 与 pgvector 入库
- [x] S1-4 混合检索 + RRF ★
- [x] S1-5 Rerank 接入
- [x] S1-6 带引用回答 + 拒答 ★
- [x] S1-7 自测用例与效果抽查 20–30 条 ★

### 阶段 2：基础框架（M1）
- [x] S2-1 数据模型与迁移（第一批）
- [x] S2-2 认证 JWT
- [x] S2-3 RBAC 与数据隔离
- [x] S2-4 通用分页/排序/筛选
- [x] S2-5 笔记表与 CRUD API
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
| 1 | SCHEMA.md 中 ⚠ 标记的推断类型/索引未复核（S2-1 已逐条结案，见 spec §3） | 建表返工 | 已完成 2026-10-26 |
| 2 | API.md 存在 TODO 待定字段与待定接口 | 前后端并行开发受限 | 各对应任务定稿时 |
| 3 | 无 refresh / 登出 / token 吊销，无登录限流（S2-2 遗留） | 令牌到期前无法主动失效；暴力破解防护缺失 | 部署层或 S3-7 之后 |
| 4 | `users` 表仍无业务数据（注册已可用，等待 S2-3/S2-11 真实使用） | 家长-学生关系与权限演示缺素材 | S2-3 起按需创建 |
| 5 | 无家长-学生绑定管理接口（S2-3 只做「已绑定则放行」判断） | 绑定只能靠 SQL/后续卡，家长看不到学生数据 | S2-11 起按需补（前端家长视角需要时） |
| 6 | 无越权审计日志（S2-3 遗留） | 越权尝试只返回 403，无落库记录 | S3-7 之后随 `audit_logs`/`llm_call_logs` 一起 |
| 7 | 权限判定未缓存：每个受保护请求多一次 `user_relations` 查询 | 量小可接受；高并发时是额外 RTT | 有性能需求时再加缓存 |
| 8 | 分页 `total` 依赖 count，深分页 offset 也随页码线性变慢（S2-4 遗留） | 数据量上万后列表接口延迟上升 | 有真实数据量后改 keyset/cursor 分页 |
| 9 | 分页只支持单字段排序，无 `pages`/`links`（S2-4 遗留） | 前端需自行算总页数；复杂排序要前端二次处理 | 需求出现时再扩 |
| 10 | 笔记 `q` 是 ILIKE 子串匹配，未接 jieba/tsvector（S2-5 遗留） | 数据量上万后慢；无语义与分词召回 | S3 检索服务化时统一切到 tsvector + 向量 |
| 11 | 笔记软删无回收站，行与正文仍占存储（S2-5 遗留） | 误删只能改库恢复；存储不释放 | 前端回收站需求出现时补恢复/彻底删除 |
| 12 | 只有「我的笔记」列表，没有「按学生列笔记」的家长/老师视角（S2-5 遗留） | 家长只能点开已知 note_id，无法浏览孩子笔记 | S2-12 前端联调或家长端卡 |
| 13 | `note_kps` 只建表，无对齐/待确认接口；`files` 有表无上传接口（S2-5 遗留，S2-6/S2-10 承接） | 知识点关联与文件上传暂时不可用 | S2-6 上传、S2-10 对齐 |

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
- S1-3 完成（按 §10 全流程：spec docs/spec/s1-3-embedding.md + plan docs/plan/s1-3-embedding.md，均经用户确认后实施）。交付：backend/app/ai/embedding/（base 契约 + openai_compat 批量/重试/维度校验 + local 占位 + 门面）、backend/app/utils/zh_tokenizer.py + math_dict.txt（jieba 领域词典）、backend/app/models/note_chunk.py、backend/app/core/db.py、backend/app/services/indexing.py、backend/alembic/（首个迁移 0001_s1_3）、backend/tests/{test_config,test_embedding_client,test_zh_tokenizer,test_note_chunk_model,test_indexing}.py、scripts/index_demo.py；requirements +SQLAlchemy 2.1.5 / alembic 1.20.0 / psycopg[binary] 3.3.6 / jieba 0.42.1 / pgvector 0.5.1；.env.example +Embedding 配置
- 验收证据：pytest 78/78（S1-1 20 + S1-2 24 + S1-3 34）；真实维度探测 `model=text-embedding-v4 维度=1024`；三份样张入库试卷 23 块（question 17）/ 笔记 6 块 / 教材页 9 块（question 5），合计 38 块；首轮 token 1169/588/706，首轮估算花费合计 ¥0.001231；`SELECT count(*)`=38；`tsv @@ to_tsquery('simple','函数 & 单调性')` 命中 3 行（note 102/103）；note 101 幂等复跑后仍 23 块、总数仍 38；向量距离冒烟返回 0.0000/0.3247/0.4063
- 迁移与索引：`alembic upgrade head` 通过；`\d note_chunks` 确认 `embedding vector(1024)`、`tsv tsvector`、`uq_note_chunks_note_chunk_index`；`ix_note_chunks_embedding_hnsw`（hnsw, vector_cosine_ops, m=16, ef_construction=64）、`ix_note_chunks_tsv_gin`（gin）、`ix_note_chunks_user_id`（btree）齐全
- 实测抓修 2 个真问题（记录于 D-016）：①jieba 默认把「单调性」切成「单调/性」，任务卡验收 SQL 会 0 命中 → 新增高中数学领域 userdict（45 词，freq=100000），不改分词算法；②Windows 下 Alembic 首次 psycopg 连接偶发无响应挂起 → env.py 加 `connect_timeout=5`，避免迁移命令无限等待
- 已确认偏离（D-016）：批大小 32→10（厂商 v4 单次最多 10 行）；llm_call_logs 先结构化日志、S3-7 建表后切换；只建 note_chunks 不加 FK（S2-1 补）；同步 Embedding 客户端；jieba 词典调优
- 文档同步：DECISIONS D-016、SCHEMA §0 维度定稿 + §4.3 FK 延后说明、spec §6/§10/§11/§15 实测回填、AGENTS §9.6 Embedding 锚点、PROGRESS

### 2026-10-20
- S1-4 完成（按 §10 全流程：spec docs/spec/s1-4-retrieval.md + plan docs/plan/s1-4-retrieval.md，均经用户确认后实施）。交付：backend/app/ai/rag/retriever.py（向量/全文/RRF/ user_id 下推/维度校验/结构化日志）、backend/app/utils/zh_tokenizer.py +`build_tsquery_or`、backend/tests/{test_retriever,test_db}.py + test_zh_tokenizer 追加、scripts/retrieval_eval.py（10 问三路 top5 + hit@5/MRR@5）；eval/results/s1-4-retrieval-eval.txt 与 empty-user 对照（学校名已脱敏为“某中学”）
- 验收证据：pytest 93/93（S1-1 20 + S1-2 24 + S1-3 34 + S1-4 15）；真实 38 块；10 问 vector 10/10 MRR 0.900、fulltext 9/10 MRR 0.725、hybrid 10/10 MRR 0.933；`--user-id 999` 三路 0/10；RRF 抽查 Q1 `note=102 chunk=1` v=1 f=1 → 2/61≈0.03279、Q3 `note=101 chunk=19` v=1 f=5 → 1/61+1/65≈0.03178
- 已知不足（不粉饰）：hybrid 仅比纯向量 MRR 高 0.033，未达任务卡“明显更好”；Q6 分段函数从纯向量第 1 掉到混合第 3（全文 OR 把 `f`/`1` 噪声块抬升）；38 块使 hit@5 饱和。S1-5 用 rerank/查询停用词再评估，本卡不事后调参
- 环境修复：Windows localhost 先解析 ::1、Docker 仅发布 IPv4，psycopg 无超时卡死；DATABASE_URL 改 127.0.0.1 + engine connect_timeout=5，test_db.py 守卫；S1-3 验收 SQL 保持 `&`，S1-4 新增 OR 查询
- 偏离（已记录 D-017）：subject_id/kp_ids 延后 S2-1（传参抛 RetrievalFilterUnavailable）；两路串行（同一 Session 非线程安全，38 块可忽略）；无 rerank/API/SCHEMA/新依赖
- 文档同步：DECISIONS D-017、spec §18 实测回填、AGENTS §9.6 retriever 锚点、PROGRESS
- S1-5 完成（按 §10 全流程：spec docs/spec/s1-5-rerank.md + plan docs/plan/s1-5-rerank.md，均经用户确认后实施）。交付：backend/app/ai/rerank/{client.py,__init__.py}（RerankClient 契约 + DashScope qwen3-rerank + Local 占位 + lru_cache 门面；批量/3600 token 截断/30s 超时/2 次重试/费用估算）、backend/app/core/config.py +10 个 RERANK_* 配置与 Key 回退、retriever 新增 `rerank_fused()` 与 `retrieve_hybrid_reranked()`（RRF 全量保留，top30→top6；失败回退 fused[:6]）、scripts/retrieval_eval.py 四路评测、backend/tests/{test_rerank,test_retriever,test_config,test_eval_script}.py
- 语料扩展：新增 3 份合成样张（指数/对数函数笔记 7 块、导数教材页 10 块、三角/数列试卷 20 块），语料从 38 块 / 3 note 扩到 **75 块 / 6 note**（101–106）；新增 104–106 明确为合成样张，不是真实学生数据
- 验收证据：pytest **124/124**（S1-1 20 + S1-2 24 + S1-3 34 + S1-4 15 + S1-5 31；多出的 10 条是执行中补的边界回归：Windows 控制台 UTF-8、响应顶层非对象、usage.total_tokens 异常、index 越界、429 Retry-After、4xx 不回显正文、tiktoken 加载失败可降级、非 RerankError 不吞、门面构造失败回退、返回条数不足）。真实四路 10 问：vector hit@5=10/10 MRR 0.900；fulltext 9/10 MRR 0.720；hybrid 10/10 MRR 0.920；rerank 10/10 MRR 0.950；rerank fallback=0/10，平均 194ms，10 问总费用 ¥0.015630
- 人工验收（用户确认）：7/10 更相关（Q1 定义域、Q2 单调性定义、Q3 证明、Q5 二次最值、Q6 分段 f(f(-1))、Q7 x+1/x 证明、Q10 利润建模），2/10 更差（Q4 奇偶性、Q9 原点对称，封面/错题本噪声进入 top5），1/10 持平（Q8 奇函数解析式）；刚好达到 ≥7/10 验收线，不调问题/关键词
- 实测抓修：Windows 下 stdout 默认 GBK，样张中的 `✗` 触发 `UnicodeEncodeError`，评测在打印 Q1 时中断；在 eval 脚本加 `_configure_stdio()` 强制 UTF-8 + `errors="replace"`，并补 `test_eval_script.py` 回归。属输出层修复，不影响检索/Rerank 结果
- 已知不足（不粉饰）：75 块仍小且 hit@5 已饱和，rerank 的 MRR 仅比 hybrid 高 0.030；Q4/Q9 关键词仍命中但 top5 噪声变多；104–106 为合成样张，论文数据需用真实材料重跑。无 API/SCHEMA/新依赖改动
- 文档同步：DECISIONS D-018、spec §15 实测回填、AGENTS §9.6 Rerank 锚点、PROGRESS；评测输出中的真实校名/姓名已替换为“某中学/某老师”

### 2026-10-20（S1-6）
- S1-6 完成（按 §10 全流程：spec docs/spec/s1-6-answer.md + plan docs/plan/s1-6-answer.md，均经用户确认后实施）。交付：backend/app/ai/llm/（base/errors/openai_compat/门面；DashScope compatible-mode + qwen-plus，httpx，超时/重试/usage/费用，错误不回显正文）、backend/app/ai/rag/prompt_builder.py（去重/按 rerank 排序/4,000 token 截断/编号/引用元数据）、backend/app/ai/rag/answerer.py（τ 拒答/引用校验/一次重试/拒答统计）、backend/app/ai/prompts/qa_v1.md（附录 C1，Jinja2）、scripts/ask.py（单问+交互）、scripts/calibrate_refusal.py（10+5 题，不调 LLM）；Settings/.env.example/requirements（jinja2 3.1.6）；`setup_logging` 增加 stderr 流
- 语料：新增 note 107 合成样张《高中数学笔记：数列求和（错位相减法）》，8 块；全库 **83 块 / 7 note**；`错位相减` 命中 5 行。note 107 不是真实学生数据
- 验收证据：pytest **160 passed, 1 warning**（基线 124 + 新增 36）；真实 qwen-plus 两个 CLI：错位相减问题 `refused=否`、4 条引用全部 note 107、llm_calls=1、prompt/completion=945/356、latency 9361ms、cost ¥0.001468；天气问题 `refused=是`、reason=low_score、llm_calls=0。证据：eval/results/s1-6-qa-demo.txt
- 阈值校准：0.35 实测无法分开（应答题 top1 最低 0.4586，应拒题最高 0.4347，“天气”0.3780），经用户确认改为 **τ=0.45**；这是 10+5 小样本暂定值，完整 20+10 留 S1-7 复核。证据：eval/results/s1-6-refusal-calibration.txt
- 实测抓修：`index_demo.py` 在 GBK 控制台打印 `¥` 时抛 UnicodeEncodeError（数据已入库）；S1-6 的 ask/calibrate 增加 `_configure_stdio()` 强制 UTF-8；`calibrate_refusal.py` 补 argparse，避免 `--help` 误跑真实检索；校准输出中的校名用通用正则替换为“某学校”
- 已知限制/风险：引用无标题/文件名（S2 补）；τ=0.45 与应答题最低 0.4586 只差 0.0086，间隔窄；引用校验只查编号存在性，不判断语义支撑；无 API/SCHEMA/迁移改动
- 文档同步：DECISIONS D-019、spec §15 实测回填、AGENTS §9.6 LLM/Answerer 锚点、PROGRESS；未提交 DOCX 样张与 .env

### 2026-10-21（S1-7）
- S1-7 完成（按 §10：spec docs/spec/s1-7-eval.md + plan docs/plan/s1-7-eval.md，均经用户确认）。交付：eval/qa_eval.py（Pydantic 数据模型、JSONL/配置校验、hit@5/MRR/引用/拒答/聚合纯函数）、eval/run.py（三配置 CLI，vector/hybrid 只检索，hybrid_rerank 走生产 answerer）、eval/configs/*.json、eval/datasets/qa_set.jsonl、eval/datasets/qa_set.candidates.md、docs/EVAL_S1.md、backend/tests/test_eval_{dataset,metrics,run}.py
- 数据：30 条 = 20 应答题 + 10 应拒题；覆盖 83 块 / 7 note。gold 采用 **AI 预标注 + 用户确认**（不是纯人工标注），候选清单为 fused top10 + 全量 83 块目录；该方式有选择偏差，文档已写明
- 真实三配置（2026-10-21 本机）：vector hit@5=1.000 MRR=0.917 检索 198ms；hybrid hit@5=1.000 MRR=0.827 检索 197ms；hybrid_rerank hit@5=1.000 MRR=0.938 检索 440ms、引用精确率 0.827、引用命中率 1.000、拒答准确率 100%（TP10/FP0/FN0/TN20）、回答平均 6243ms、平均 945.5 tokens、总费用 ¥0.0317224、llm_calls=24、citation_retry=2
- 失败/偏差：q001 引用精确率 0.200（5 引用仅 1 gold），q003 0.667，q004 0.500，q005 0.667，q007 0.500，q010 0.500，q016 0.500；q004/q005/q009 属弱证据题；q026/q029 最终拒答正确但已调 LLM（1277/1235 tokens）。详见 docs/EVAL_S1.md
- 验收证据：pytest **191 passed, 1 warning**（S1-6 基线 160 + 新增 31）；三份 JSON/Markdown 真实落盘；`eval/run.py --help` 退出 0；数据校验 30 条/10 拒答
- 已知限制：hit@5=1.000 受预标注参考候选清单影响，不能外推；样本 30 条/83 块；纯向量延迟复用混合检索调用；回答链路内部重复检索一次；引用精确率不等于答案数学正确
- 文档同步：DECISIONS D-020、spec §15、PROGRESS、docs/EVAL_S1.md；无 API/SCHEMA/迁移/新依赖
- 里程碑：本地 tag `m0-rag-validated`；用户负责 push

### 2026-10-26（S2-1）
- S2-1 完成（按 §10 全流程：spec docs/spec/s2-1-data-model.md + plan docs/plan/s2-1-data-model.md，均经用户确认）。交付：backend/app/models/enums.py（UserRole / EdgeRelation / EdgeSource + in_check）、5 个模型（user / user_relation / subject / knowledge_point / knowledge_edge）与 __init__ 注册、backend/alembic/versions/0002_s2_1_business_tables.py、backend/tests/test_models_s2_1.py（15 条）、scripts/smoke.py 的 REQUIRED_TABLES
- 拍板与偏离（D-021）：表数 7→5（roles / user_roles 不建，以 SCHEMA 的 users.role 单列枚举为准）；S2-2 认证改走 FastAPI 官方安全示例（fastapi-users 的 SQLAlchemy 适配器 async 专用且基础字段与 SCHEMA 不符）；枚举一律 TEXT+CHECK；note_chunks 外键延后到 S2-5
- 验收证据：pytest **206 passed, 1 warning**（S1 基线 191 + 新增 15）；`alembic upgrade head`（0001→0002）→ `\d` 五表字段齐全（knowledge_points.embedding 为 vector(1024)、HNSW m=16/ef_construction=64）、5 个 UNIQUE、7 条 CHECK、6 个 FK、6 个业务索引；`alembic downgrade -1` 回到 0001（5 表消失、note_chunks 83 行保留）；再次 `upgrade head` 通过
- 负向验证（事务内制造违规后 ROLLBACK，库内零残留）：非法 role → `ck_users_role`；重复 username → `uq_users_username`；自环边 → `ck_knowledge_edges_not_self`；删除被引用学科 → `fk_knowledge_points_subject_id`；level=5 → `ck_knowledge_points_level`
- 冒烟：`scripts/smoke.py` 8 项中 7 PASS + 1 SKIP（前端 dev 未启动，可选组件），核心表 6/6，退出码 0
- 已知事项（不粉饰）：users 表暂无数据，note_chunks 的 user_id 外键仍待 S2-5 回补；updated_at 由应用层 onupdate 维护，裸 SQL 更新不会刷新；knowledge_points.embedding 全为 NULL，待 S2-10 对齐时写入
- 文档同步：SCHEMA.md（§0 数组字段定稿、5 表时间列/索引/约束、§4.3 FK 口径、§10.1 role 定稿）、AGENTS.md（§4 枚举规则、§9.6 模型锚点）、DECISIONS D-021、PROGRESS

### 2026-10-26（S2-2）
- S2-2 完成（按 §10 全流程：spec docs/spec/s2-2-auth.md + plan docs/plan/s2-2-auth.md，均经用户确认）。交付：backend/app/core/security.py（Argon2id 哈希、PyJWT HS256 签发/解析、启动密钥校验）、backend/app/api/deps.py（get_db / HTTPBearer / get_current_user）、backend/app/services/auth_service.py（注册、认证、签发）、backend/app/schemas/auth.py（RegisterRequest / LoginRequest / UserOut / TokenOut）、backend/app/api/v1/auth.py + api/router.py、main.py 装配、4 个测试文件
- 拍板（D-022，2026-10-26 用户确认）：依赖 pwdlib[argon2]==0.3.1 + PyJWT==2.15.1；登录走 JSON + HTTPBearer + 统一壳（不用 OAuth2 表单）；注册可选 student/teacher/parent、admin 由 Literal 拒绝；单 token 24h、无 refresh/登出；登录失败统一文案 + 假哈希抹时间差；重名靠 DB UNIQUE + IntegrityError→409/40900
- 验收证据：pytest **237 passed, 1 warning**（S2-1 基线 206 + 新增 31：配置 4 / 安全原语 10 / 服务 6 / 接口 11）；真实 uvicorn + curl：注册 201（`username=test_user_1`、无 `password_hash`）、重复注册 409/40900、`role=admin` 422/42200、登录返回 164 字符 token、`/auth/me` 200 回显用户、无 token「未提供认证凭据」/错密码与未知用户同为「用户名或密码错误」/过期 token「登录已过期，请重新登录」/乱码 token「无效的认证凭据」全部 401/40100；登录耗时 0.269–0.277s、未知用户 0.260–0.289s（时间差已抹平）
- 数据库核验：`password_hash` 前缀 `$argon2id$v=19$m=655`；验收后删除测试账号，`users` 计数 0
- 已知事项（不粉饰）：无 refresh/登出/吊销与登录限流（见遗留 3）；Argon2id 单次登录约 270ms；用户名大小写归一为小写（`Alice`=`alice`）；token 内 role 不作为权限来源，S2-3 必须基于回表用户判断
- 文档同步：API.md（§0 Bearer 约定、§1 三条接口定稿、§12 TODO 更新、§13 增 40900）、AGENTS.md（§9.6 路由 + 认证锚点）、DECISIONS D-022、PROGRESS、.env.example（AUTH_*）、requirements.txt

### 2026-10-26（S2-3）
- S2-3 完成（按 §10 全流程：spec docs/spec/s2-3-rbac.md + plan docs/plan/s2-3-rbac.md，均经用户确认）。交付：backend/app/core/permissions.py（`require_role` / `require_student_access` / `ensure_student_access` / `can_access_student` / `has_student_relation`）、backend/tests/test_permissions.py（13 条）、backend/tests/test_permissions_api.py（10 条，含硬验收）
- 拍板（D-023，2026-10-26 用户确认）：验收载体 = 依赖 + pytest，**不新增生产接口**（本卡没有可打的真实学生数据端点，curl 证据留 S2-5）；**admin 不绕过**学生数据权限，管理端只走 `require_role("admin")`；查看方限 parent/teacher；越权统一 403/40300「无权访问该资源」不泄露存在性；依赖而非装饰器；角色与绑定关系以数据库为准
- 验收证据：pytest **260 passed, 1 warning**（基线 237 + 新增 23）；硬验收用例 `tests/test_permissions_api.py::test_b_cannot_read_a_notes_returns_403` PASSED（HTTP 403 + code 40300 +「无权访问该资源」）；正向 A 读自己 200、已绑定家长/老师 200；反向 未绑定家长/老师 403、admin 读学生数据 403、学生读管理接口 403、无 token 401、未绑定家长访问不存在学生仍 403
- 已知事项（不粉饰）：本卡无 curl 证据（无生产接口）；无绑定管理接口（遗留 5）；无越权审计日志（遗留 6）；权限判定未缓存（遗留 7）
- 文档同步：API.md（§0 角色与数据范围矩阵 + 隔离规则）、AGENTS.md（§9.2 学生数据接口约定、§9.6 权限锚点）、DECISIONS D-023、PROGRESS；无 API 端点/SCHEMA/依赖变更

### 2026-10-26（S2-4）
- S2-4 完成（按 §10 全流程：spec docs/spec/s2-4-pagination.md + plan docs/plan/s2-4-pagination.md，均经用户确认）。交付：backend/app/schemas/common.py 新增 `PageData[T]`（`{items,total,page,page_size}`）、backend/app/utils/pagination.py（`PageParams` / `SortParams` / `page_params` / `sort_params` / `paginate_query` / `apply_sort`）、backend/tests/test_pagination.py（12 条）、backend/tests/test_pagination_api.py（8 条）
- 拍板（D-024，2026-10-26 用户确认）：引入 `fastapi-pagination==0.16.1`（只新增 1 包、无版本冲突）；响应固定 4 字段 + query `page`/`page_size`，库的 `size`/`pages` 不泄露；`page_size` 上限 100；排序白名单映射防注入；默认排序由各接口传 `default_sort`；筛选只用显式参数；测试用 SQLite 内存库真执行
- 验收证据：pytest **280 passed, 1 warning**（基线 260 + 新增 20）：分页 12 条（默认参数、第 1/2 页、超末页空列表、出参模型转换、升降序、非法字段/方向、无默认排序不改写语句、默认排序生效）；接口 8 条（`data` 恰为 4 键且无 pages/size、第 2 页 id 正确、page=0 与 page_size=101 → 422/42200、未知排序字段 422/42200、order 非法 422/42200、按 name 升序、total 跨页稳定）
- 已知事项（不粉饰）：本卡无生产列表接口，**没有 curl 证据**，复用验收在 S2-5（笔记列表）与 S4（错题/题目列表）补；深分页 count/offset 成本（遗留 8）；单字段排序、无 pages/links（遗留 9）
- 文档同步：API.md（§0 分页/排序两行定稿）、AGENTS.md（§9.2 列表接口约定、§9.6 分页锚点）、DECISIONS D-024、PROGRESS、requirements.txt；无 API 端点/SCHEMA 变更

### 2026-10-26（S2-5）
- S2-5 完成（按 §10 全流程：spec docs/spec/s2-5-notes-crud.md + plan docs/plan/s2-5-notes-crud.md，均经用户确认）。交付：迁移 `0003_s2_5_note_tables.py`（建 files/notes/note_kps + 清理孤儿 + 补 note_chunks 三个外键）、模型 `file.py`/`note.py`/`note_kp.py`、`app/utils/markdown_text.py`、`app/schemas/notes.py`、`app/services/note_service.py`、`app/api/v1/notes.py`、`tests/test_markdown_text.py`（11）、`tests/test_note_service.py`（18）、`tests/test_notes_api.py`（13）
- 拍板（D-025，2026-10-26 用户确认，全部选 A）：一次建 files/notes/note_kps；`uq_files_user_sha256 (user_id, sha256)`；迁移前条件删除 83 行无主 note_chunks 再补外键；PATCH 部分更新 + DELETE 204 软删；列表仅本人、详情本人或已绑定家长/老师、写删仅本人且仅 student（admin 不绕过）；`q` 走 ILIKE 并转义；`content_text` 去公式派生；`subject_id` 先查存在性；标签 `TEXT[]`；列表出参 `NoteSummary`（无正文）
- 验收证据：pytest **322 passed, 1 warning**（基线 280 + 新增 42）；`alembic upgrade head` 输出 `Running upgrade 0002_s2_1 -> 0003_s2_5`，psql 核验 note_chunks 由 83 → 0、三个 FK 就位、notes 含 GIN 标签索引；`alembic check` 输出 `No new upgrade operations detected.`；真实 curl：建 201（psql 落库 `content_text=设 则`）→ 列表 total=1 且仅 4 个分页键 → A 详情 200 → **B 读 A 的笔记 403/40300**（补上 S2-3 的真实接口证据）→ q/tag/subject_id 筛选命中、不存在关键词 0 条 → `sort_by=content_md` 422/42200（message 列可选字段）、`page_size=101` 422 → B 改/删均 403 → PATCH 后 `updated_at` 14:20:58→14:21:23、`created_at` 不变、`content_text` 重算 → DELETE 204 → 列表 total=1（另一条）、详情 404、psql 行仍在且 `deleted_at` 非空 → 清理后 notes/users/subjects/chunks 全为 0
- 与 plan 的唯一偏差：标签过滤原写 `Note.tags.any(tag)`（`= ANY(tags)`），实测触发 SQLAlchemy 2.1 `SADeprecationWarning` 且不走 GIN，改为 PG `ARRAY.contains` → `tags @> ARRAY[tag]`；已同步 spec §2.3、plan、API.md、AGENTS §9.6
- 已知事项（不粉饰）：`q` 是 ILIKE 子串匹配（遗留 10）；软删无回收站（遗留 11）；无家长视角笔记列表（遗留 12）；`note_kps`/`files` 只有表没有接口（遗留 13）；迁移删除的 83 行实验数据不可恢复
- 文档同步：API.md（§2 五接口定稿 + §12 缺口）、SCHEMA.md（§4 表头、§4.1 sha256 定稿、§4.3 外键已补）、AGENTS.md（§9.6 笔记锚点）、DECISIONS D-025、PROGRESS、spec/plan 执行记录；无新依赖、无 .env 变更
