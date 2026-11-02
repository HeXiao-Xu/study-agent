# 项目进度

> 更新规则：每个任务完成后由 AI 更新本文件（AGENTS.md §7）；周末对照打卡表复盘。
> 总表来源：docs/AI协作开发实施计划.md 第 14 章。★ 标记为关键路径任务（做不好整项目就废，必须亲自验收）。

## 当前状态

- 阶段：阶段 0/1/2 已完成；阶段 3（RAG 问答上线，M2）S3-1～S3-9 已交付（`m2-rag-done` tag 待用户验收）；阶段 4（错题与知识图谱，M3）进行中，S4-1 已完成（tag `m0-env-ready` / `m0-rag-validated`）
- 最近完成：S4-1 题库表 + 试卷切题（迁移 `0009_s4_1`、`question.extract` 异步切题、8 个新接口、前端导入/审题两页）；后端 **853 passed, 1 warning**，前端 **122 passed / 30 files**
- 下一步：S4-2 错题录入 + 状态机；跨会话交接见 [docs/HANDOFF-S3.md](HANDOFF-S3.md)
- 已知阻塞：无。`m1-framework-done` 暂未打 tag：任务卡要求库内有 20 篇真实笔记 + 1 份试卷，当前仅有 4 篇原有笔记

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
- [x] S2-6 文件上传 + MinIO + 去重
- [x] S2-7 异步任务框架
- [x] S2-8 文档解析 Worker
- [x] S2-9 知识点树 CRUD + 导入
- [x] S2-10 知识点对齐与待确认队列
- [x] S2-11 前端登录/布局/路由守卫
- [x] S2-12 前端笔记列表与编辑器
- [x] S2-13 前端上传与解析状态
- [x] S2-14 前端知识点树管理

### 阶段 3：RAG 问答上线（M2）
- [x] S3-1 索引服务产品化
- [x] S3-2 检索服务
- [x] S3-3 Query 改写与意图识别
- [x] S3-4 上下文组装 + Prompt 版本管理
- [x] S3-5 问答 API（SSE）+ 会话落库
- [x] S3-6 拒答与引用校验
- [x] S3-7 缓存 + 调用日志 + 用量统计
- [x] S3-8 前端问答页（流式 + 引用跳转）★
- [x] S3-9 抽查扩展到线上链路 + 三种配置对照

### 阶段 4：错题与知识图谱（M3）
- [x] S4-1 题库表 + 试卷切题
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
| 13 | `note_kps` 只建表，无对齐/待确认接口（S2-5 遗留，S2-10 承接）；`files` 上传接口已由 S2-6 交付 | 已由 S2-10 交付自动对齐 + 待确认队列 | 已完成 |
| 14 | 上传去重必须读完整个文件才算 sha256（S2-6 遗留） | 60MB 文件要 1–2 秒才返回；无法“秒回” | 需求出现时改为客户端预哈希 |
| 15 | 文件只有扩展名 + 头部 magic 校验，无病毒扫描/图片重编码（S2-6 遗留） | 合法容器内嵌恶意内容检测不到 | 上线前按需接扫描 |
| 16 | 无文件列表/下载/删除接口，`presigned_get_url` 只在存储层（S2-6 遗留） | 前端无法直接列出/下载已传文件 | S2-12 笔记插图时补签名 URL 接口 |
| 17 | `parse_status` 只有 `pending`，无 `error_msg` 列（S2-6 遗留） | 解析进度与失败原因还看不到 | S2-8 迁移 + Worker 回写 |
| 18 | Worker 崩溃后 `running` 行无心跳回收（S2-7 遗留） | 任务会卡在 running，需人工改库 | 后续卡加心跳/超时回收 |
| 19 | 无任务列表/取消/重跑接口（S2-7 遗留） | 前端只能按 id 轮询 | 有需求时补 |
| 20 | 单队列、无优先级；`demo.sleep` 是验收入口（S2-7 遗留） | 正式前端不应暴露 demo 入口 | S2-8 起只内部复用 `create_task` |
| 21 | 提交用 `asyncio.run` 建短连接（S2-7 遗留） | 高频提交会浪费 Redis 连接 | 量级上来再改连接池 |
| 22 | 解析与 embedding 共用 300s job timeout，无分页续跑（S2-8 遗留） | 超大 PDF 会超时失败，需重新上传 | 有真实大文件需求时按页分批/延长超时 |
| 23 | 图片/扫描件不支持，直接 failed（S2-8 遗留） | 拍照错题无法入库 | S3 OCR 卡 |
| 24 | 文档笔记与上传文件无删除联动（S2-8 遗留） | 删笔记不删文件；删文件无接口 | 文件管理接口一起补 |
| 25 | 解析重试会让文件状态短暂在 failed/parsing 抖动（S2-8 遗留） | 前端可能闪一次失败提示 | 前端按 task 终态判定或加“重试中”标记 |
| 26 | `parse_progress` 是阶段值，不是页级；Docling 首轮约 3 分钟（S2-8 遗留） | 用户看不到细粒度进度，首轮体感慢 | 需要时加页级回调/预热 |
| 27 | 高中数学种子树是 AI 草稿，考点归属与 `exam_weight` 未经教研校对（S2-9 遗留） | 对齐/组卷权重可能偏差 | 用户人工校对 `backend/data/kp_math.json` 后 overwrite |
| 28 | 知识点无拖拽/批量排序，`order_no` 无唯一约束（S2-9 遗留） | 前端调整顺序需逐节点 PATCH；同序按 id 兜底 | S2-14 前端树管理时按需补批量接口 |
| 29 | 导入 overwrite 直接改库，无自动备份/并发锁；append 假设完整树（S2-9 遗留） | 误删只能靠备份；并发导入第二个报唯一冲突；部分树会重置 level | 覆盖前 `pg_dump`；批量导入串行执行 |
| 30 | 对齐关键词只匹配节点全名/去前缀核心词，无别名/同义词表；树先验只是 tags/title 近似（S2-10 遗留） | 同义表述漏召回；本次 30 条中 5 条未产生任何关联 | 收真实笔记后补别名表/按学科调阈值 |
| 31 | 对齐阈值 0.75/0.55 基于 text-embedding-v4 分数分布（S2-10 遗留） | 换 Embedding 模型需重新校准，可能大量进待确认或大量丢弃 | 换模型时用标注集重跑 ROC 选阈值 |
| 32 | `note_kps` 无时间列/审计表，忽略即删除；并发重跑同一笔记可能 pkey 冲突（S2-10 遗留） | 无法按时间排序/追溯，忽略项重跑可能再现 | 需要时补 `created_at/updated_at` 迁移与审计表 |
| 33 | 对齐 LLM 失败即任务失败，无纯算法兜底（S2-10 遗留；S3-7 已把 `kp_align` 调用写入 `llm_call_logs`） | 无 Key/额度时对齐不可用 | 如需降级再设计兜底分数 |
| 34 | 6 个业务模块目前都是统一占位页；教师/家长登录后看到与学生相同的导航（S2-11 遗留） | 演示时“系统很空”，家长/教师视角未区分 | S2-12–S2-14 逐个替换；角色页等对应模块有数据后再加 `meta.roles` |
| 35 | token 存 localStorage，无 CSP/HttpOnly，无刷新 token（S2-11 沿用 S2-2） | XSS 可读 token；令牌到期前无法主动失效 | 部署层加 CSP；refresh/吊销见遗留 3 |
| 36 | Element Plus 全局注册，构建主包 1.0 MB（gzip 330 KB）（S2-11 实测） | 首次加载偏慢，内网演示可接受 | 有性能要求时改按需引入/分包，别在功能卡里顺手重构 |
| 37 | 草稿只存当前浏览器 localStorage，无服务端自动保存；陈旧判断只比 `baseUpdatedAt`（S2-12） | 换设备/清缓存丢失；同毫秒并发更新可能漏判 | 需要多端草稿或实时协作时再做服务端草稿 |
| 38 | 笔记只有列表 + 直接编辑页，无只读阅读页、文件夹、标签筛选、版本历史、回收站（S2-12） | 长文阅读/整理能力弱；误删无法前端恢复 | 需求出现时补阅读页与文件夹/标签筛选 |
| 39 | 图片以 `note-file://<id>` 存在 Markdown 正文，脱离本应用导出会破图；取图一次读入内存、无压缩/缩略图、删笔记不删图（S2-12） | 导出不通用；大图多图有内存压力；孤儿文件占存储 | 导出前做 token→公开 URL 转换；文件管理卡补压缩/删除联动 |
| 40 | 编辑页懒加载 chunk 约 405 KB（gzip 140 KB），KaTeX/md-editor 体积大（S2-12 实测） | 首次进入编辑页偏慢，内网可接受 | 有性能要求时拆 KaTeX/CodeMirror 或预加载 |
| 41 | 教师/家长不能进笔记工作区（路由 `roles:['student']`），其读取能力未做前端入口（S2-12 沿用 S2-11） | 家长/教师视角仍空白 | 家长/教师端卡再设计入口与只读模式 |
| 42 | 文件页只接受 `.pdf/.docx/.md/.txt`，图片仍走笔记编辑器独立入口，扫描件/图片 OCR 未支持（S2-13） | 图片资料无法在文件页解析 | OCR 卡再接；先把图片当笔记插图用 |
| 43 | 无文件下载、删除、签名 URL 接口；生成笔记/切片与文件无删除联动（S2-13 沿用 S2-6） | 文件只增不减，误传无法前端清理 | 文件管理卡补删除/下载与关联清理 |
| 44 | 失败重试只保留当前页面会话里的原始 `File`；刷新后历史 failed 文件没有重试按钮（S2-13） | 刷新后只能重新选文件，体验断档 | 需要时增加服务端重解析接口或持久化任务 |
| 45 | 切片只预览前 3 条，无完整切片分页/搜索（S2-13） | 长文档只能看开头 | 后续文件详情页/切片管理卡补全量列表 |
| 46 | 上传队列不跨刷新保存，上传中不能取消；列表轮询 5 分钟后停止，超时需手动刷新（S2-13） | 离开页面丢队列；后台可能仍在解析 | 需要时用 Pinia/IndexedDB 持久化并加取消 |
| 47 | S2-10 `kp.align` 对英文长 `evidence` 超 200 字会 Pydantic 校验失败（S2-13 验收英文 PDF 时 `kp.align` failed，解析本身 succeeded） | 英文材料不触发对齐；不影响文件/切片 | 在 extractor 落库前截断/压缩 evidence，另卡修复 |
| 48 | 文件宽度沿用全局 `body min-width:1024px`；小于 1024 的窗口会出现整页横向滚动（S2-13 实测 824px；1440px 正常） | 窄屏/分屏体验差 | 移动端适配卡统一处理，不在 S2-13 改全局布局 |
| 49 | 全量重建按 `content_md` 重建，文档笔记的 `page_no/bbox_json` 被清空（S3-1 已确认代价） | 文档引用失去页码/原文高亮定位 | S3-2/S3-6 需要页码时，改为文档笔记保留解析产物重建或按来源区分 |
| 50 | 无单笔记索引状态列与单笔记重跑接口，失败只能整轮重建（S3-1） | 单篇坏笔记排障成本高、重复花钱 | 需要时加 `index_status` 列或 `index.note` 单笔记接口 |
| 51 | 同一笔记并发索引可能撞 `uq_note_chunks_note_chunk_index`，靠 runner 3 次重试（S3-1） | 极端并发下任务短暂失败；重试仍失败只进重建 failures | 有并发编辑需求时加 advisory lock 或按笔记防抖 |
| 52 | 重建费用与耗时随笔记量线性增长，无增量重建（S3-1） | 笔记多时全量重建较贵 | 后续按 `updated_at` 增量或只重建指定笔记 |
| 53 | 文档笔记 `subject_id` 为 NULL（S2-8 未回填），带 `subject_id` 的检索不命中它们（S3-2） | 按学科过滤会漏掉上传文件生成的笔记 | 文件级学科元数据回填卡处理，不猜数据 |
| 54 | `folder` 是 `notes.folder` 自由文本，无 notebook 表/层级（S3-2） | 改名等于换 scope；前端无法做文件夹树 | 需要笔记本树时新建表并迁移 |
| 55 | P95 受外部 Embedding 支配（实测 P50 154ms/次）；S3-7 已加 Redis 内容哈希缓存，但首次查询仍无向量 | Embedding 抖动时首查 P95 贴线 | 需要时再加批量预热/本地缓存监控 |
| 56 | `debug=true` 最多返回 3×20 条完整块文本（S3-2） | 响应体大，误开会影响前端性能 | 仅调试使用；需要时加 `debug_limit` |
| 57 | 检索不支持 kp/知识点过滤（`note_kps` 有数据但未下推）（S3-2） | 不能按知识点圈定复习范围 | 需要时加 join `note_kps` 并评估索引 |
| 58 | 意图由单次 LLM 判定且仅 4 类；10 条验收全部判为 `concept_explain`（S3-3） | 误判会走错分支/文案，但不改检索结果 | S3-5 用真实对话评估；必要时加规则或多标签 |
| 59 | 改写缓存只在进程内，不跨 worker/重启（S3-3；S3-7 只把 QA/Embedding 放 Redis，未迁移改写缓存） | 多 worker 命中率低、重复计费 | 后续卡把改写缓存换 Redis |
| 60 | 历史只留最近 3 个 user 轮、单条截 300 字（S3-3） | 长对话更早条件丢失，追问可能缺前提 | S3-5 按需调参；超长对话先摘要 |
| 61 | `LLMError` 降级时拿不到 usage，token/cost 记 0（S3-3）；S3-7 失败调用会写 `status=failed`，但 tokens/cost 仍为 NULL | 失败调用成本不透明 | 需要时在适配器层记录失败请求的预估用量 |
| 62 | 指代追问验收 hit@3=9/10；第 6 条改写正确但检索未召回 `note 77/chunk 11`（S3-3） | 单条追问仍可能答非所问 | 检索侧调权重/召回，不改写侧粉饰 |
| 63 | 无 HTTP 接口/前端，S3-5 接入前只能脚本验收（S3-3） | 前端暂不可用 | S3-5 接会话 API |
| 64 | Prompt 版本无删除/停用/归档接口，历史只增不减（S3-4） | 长期积累脏版本；误建无法清理 | 需要时加 admin 归档/软删，不做物理删除 |
| 65 | 只有 QA Prompt 走库；`rewrite_v1.md`、`kp_align_v1.md` 仍读文件（S3-4） | 三类 Prompt 管理方式不统一 | 后续卡迁 rewrite/kp，统一 `prompt_service` |
| 66 | 每次问答多一次 `prompt_templates` active 查询，无缓存（S3-4） | 高并发多一次 DB 往返 | S3-7 加 Redis 短 TTL，并带版本失效 |
| 67 | `variables_json` 只校验类型/非空，不校验模板实际引用了哪些变量（S3-4） | 元数据可能和正文不一致 | 保存时用 Jinja2 AST 提取变量并与元数据比对 |
| 68 | 多管理员并发激活同一 name 无重试，部分唯一索引冲突会失败（S3-4） | 并发切换可能一方报错 | 单管理员场景暂可接受；需要时加重试/串行化 |
| 69 | 行级留痕只有 `created_by/created_at/updated_at`，无完整操作审计日志（S3-4） | 只能知道谁建，不能还原启用操作序列 | S3-7 `llm_call_logs`/运维审计补事件日志 |
| 70 | S3-5 只持久化合法 `[n]` 子集，不做引用校验/重试/拒答补丁（S3-5） | 模型漏引或无依据陈述仍会入库 | S3-6 已由 `citation_checker` 接管 |
| 71 | 会话只支持创建与续聊，无列表/删除/重命名接口（S3-5） | 前端无法管理历史会话 | S3-8 前端问答页一起补 |
| 72 | SSE 无 429 限流（S3-5）；S3-7 已让 LLM/Embedding 成功/失败调用写 `llm_call_logs`，但限流仍未做 | 高频请求仍可能打满上游 | 后续卡统一限流 |
| 73 | 真实验收使用本机 DashScope `qwen-plus`，未做并发压测（S3-5） | 单路延迟 3.7–24.5s，并发表现未知 | 上线前按并发目标压测 |
| 74 | 引用校验后输出，首字延迟从“立即”变为完整生成后（S3-6 实测 meta 3.10s、首个 delta 15.06s） | 前端需要更明显的 loading 态，长答案体感慢 | S3-8 前端补加载态；需要时再评估流式校验替代方案 |
| 75 | 块级检测是启发式，不判断引用是否真正支持该句；列表/段落内只有末尾一个引用会视为整块已引用（S3-6） | 可能漏掉“引用与陈述不匹配”或段落内部分句子无依据 | 后续用 LLM 逐句归因或引用蕴含校验 |
| 76 | 拒答建议固定文案，`note_id` 为 null，且不落库（S3-6） | 建议不个性化，刷新后丢失 | S3-8 如需历史建议，加列/JSONB 并与 kp 关联 |
| 77 | 断连在静默生成阶段只能等下一次 chunk 到达才关闭上游（S3-6） | 立即停止计费无保证 | 需要时把 LLM 适配器改 async 取消 |
| 78 | 题目 `difficulty` 由 LLM 主观判断，真机 20 题实测集中在 1–3（S4-1） | 组卷按难度配额选材时可选区间被压缩 | S5-1 组卷前用真实卷校准，或加人工难度修正 |
| 79 | `stem_latex` 本次未落库（保留 NULL）（S4-1） | “整题单公式”场景没有独立 LaTeX 字段，前端只渲染 `stem_md` | 出现公式题专用排版需求时补提取/编辑 |
| 80 | 知识点对齐是近似的：复合题通常只挂 1–2 条，真机 20/20 题挂上、共 32 条（S4-1） | 跨章节题的薄弱点定位不完整 | 后续补别名表/按学科调召回，或做人工确认队列 |
| 81 | 扫描版 PDF 仍不支持，`question.extract` 直接 failed（S4-1） | 拍照/扫描试卷无法入库 | S4-2 拍照识别（多模态） |
| 82 | 题库是公共语料且无审核流，任何登录用户可见全部题（S4-1） | 学生导入的低质量题会进入公共池 | 需要时加审核/可见范围 |
| 83 | 合并/拆分/删除均为硬删，操作不可撤销（S4-1） | 误操作只能重新导入或手工重录 | 前端已二次确认；需要时补软删/回收站 |
| 84 | 试卷原件留在 `files` 表，文件页与普通附件混排，无用途区分（S4-1） | 文件列表被试卷占位 | 文件管理卡按用途加筛选或分栏 |
| 85 | 判重只拦同哈希与近似重复（cos ≥ 0.92），不拦“变式题”（S4-1） | 同题换数字会作为新题入库 | 变式识别留给组卷/错题去重 |

## 变更日志

### 2026-11-03（S4-1）
- S4-1 完成（按 §10 全流程：spec `docs/spec/s4-1-question-bank.md` + plan `docs/plan/s4-1-question-bank.md`，均经用户确认）。交付：迁移 `0009_s4_1` 与 `models/question.py`、`models/question_kp.py`；`ai/extract/{splitter,question_extractor}.py` + `ai/prompts/question_extract_v1.md`；`services/question_service.py`；`tasks/question_extract.py`；`api/v1/questions.py` + `schemas/question.py`（8 个新路由 + 复用 `GET /tasks/{task_id}`）；`file_service` 放宽 `parse=false`；前端 `views/questions/{ImportView,ReviewView}.vue`、`api/questions.ts`、路由与导航（04 题库）；自编 20 题验收卷与生成脚本。
- 拍板（D-044）：题库为公共语料；`questions.stem_hash` + `UNIQUE(subject_id, stem_hash)` 为判重第一道闸、余弦 0.92 为第二道；切题允许部分成功（单题失败进 `failed_items`，任务仍 `succeeded`）；知识点对齐改为「向量 top-10 候选内由 LLM 选择」，0.75 只作 LLM 失败时的确定性兜底；拆分/合并判重必须 `exclude_ids` 排除源题自身。
- 测试：后端 **853 passed, 1 warning**（S3-9 基线 770）；前端 **122 passed / 30 files**（S3-8 基线 114/29）。
- 真机验收（真实 Qwen + 真实 Postgres/Redis/MinIO + 本人自编 20 题卷，2026-11-03）：

  | 项 | 实测 |
  |---|---|
  | 首次导入（修复后干净全量跑） | 任务 id 98，`succeeded`，`detected=20 / expected=20 / created=20 / duplicated=0 / failed_items=[] / degraded=false / warnings=[]`，`elapsed_ms=131948`（**132.5s**） |
  | 二次导入（幂等） | `created=0 / duplicated=20`，耗时 **80.3s** |
  | 知识点覆盖 | **20/20 题全部挂上**，共 **32 条**链接（1 条×12 题、2 条×4 题、3 条×4 题） |
  | 题型与难度 | 单选 8 / 填空 4 / 解答 8；`difficulty` 1 分×4、2 分×12、3 分×4；`verified` 全为 `true`（答案取自卷面【答案】） |
  | 编辑 1 题 | PATCH 改答案/难度后持久化，重新 GET 读到新值 |
  | 删除 1 题 | **204**；删除后 `question_kps` 残留行数 **0** |
  | 删 1 题后重导 | `created=1 / duplicated=19`，题数恢复 20 |
  | 难度非法值（9） | `422/42200` |
  | PNG 导入 | `400/40000`（仅支持 PDF/DOCX） |
  | 拆分 1 题 | `{"split_at":"（2）"}` → **200** 返回 2 道题，原题随即 `404`，题库题数 +1；左半挂「通项公式与性质」、右半挂「数列求和」（按半题重新对齐） |
  | 合并 2 题 | **200** 返回新题 id 45，原 2 题随即 `404`；合并题挂 3 条知识点（「一元二次函数」「平面向量与复数」「平面向量基本定理与坐标表示」），拼接后重新对齐 |
  | 合并参数非法 | 只给 1 道题 → `422/42200`；含不存在/跨学科 id → `422/42200` |

- 实施中的修正（真机发现）：`check_duplicate` 原实现未排除源题自身，拆分/合并时源题仍在库，子串/拼接与原题余弦 ≥0.92，真实题拆分直接 409；已为 `check_duplicate` 增加 `exclude_ids`（split 传 `[question_id]`、merge 传 `unique_ids`），判重语义不变，并补 3 条测试。验收口径统一采用修复后的干净全量跑（上表）。

- 实测偏差（已回填 spec）：列表入参 `mine: bool`（原写 `created_by=me`）；详情只有 `kps[]`、无 `kp_ids`；队列不可用沿用 S2-7 的 `500/50000`（原写 `503/50300`）；split/merge 参数错误统一 `422/42200`（原写 `400/40000`）；`questions.created_at` 为本次新增列；知识点挂载不再以 0.75 为门禁（D-10 重写）。
- 文档同步：API.md §5.5 + §3 `parse` 说明、DECISIONS D-044、PROGRESS、AGENTS §9.2/§9.6、实施计划 S4-1 勾选与实施记录、spec 偏差回填；无新增依赖、未动 main。
- 已知不足（不粉饰）：`difficulty` 由 LLM 主观判断（实测集中 1–3）；`stem_latex` 本次未落库（NULL）；知识点对齐近似，复合题通常 1–2 条；扫描版 PDF 不支持（S4-2）；判重不拦变式题；题库公共无审核流；拆分/合并/删除硬删不可撤销。

### 2026-11-02（前端细节）
- 修复笔记、文件页重复标题：`StudentOnlyView` 的 `PageHeader` 仅在非学生拒绝页渲染，学生页只保留页面自身标题。
- 问答会话列表的“改名/删除”收进悬停出现的 `⋯` 菜单（`el-dropdown`），支持键盘 focus 与触屏常显；菜单点击不触发会话切换。
- 前端 **116 passed / 29 files**，`npm run build` 退出 0（仅 775KB chunk 警告）。

### 2026-11-02（S3-9）
- S3-9 完成（按 §10 全流程：spec `docs/spec/s3-9-online-eval.md` + plan `docs/plan/s3-9-online-eval.md`，均经用户确认）。交付：`retrieval` 三配置（vector/hybrid/hybrid_rerank）与冲突校验；`done.cost_yuan`；`eval/datasets/qa_set_m2.jsonl` 40 条；`eval/api_client.py`；`eval/run.py` 在线模式与 `--config all` 对照输出；`docs/EVAL_M2.md`。
- 拍板（D-043）：扩展现有 `/retrieval/search` 的 `retrieval` 字段；新建 M2 数据集保留 S1 数据；回答只跑生产 `hybrid_rerank`；人工核对为 AI 初核 + 用户抽查；在线评测只走 HTTP，不直连 DB；token/密码不落盘。
- 测试：新增 8 条 schema、4 条 service 分支、7 条 API、4 条数据集、7 条在线客户端、3 条在线编排；基线 735 → **770 passed, 1 warning**。
- 真实三配置（真实 Postgres + Redis + DashScope，`test1` id=18，2026-11-02 02:34–02:43）：vector hit@5 **1.000**/MRR **0.957**/检索 **14ms**；hybrid **1.000**/**0.790**/**15ms**；hybrid_rerank **1.000**/**0.978**/**14ms**。生产回答 40 条：引用精确率 **0.897**、命中率 **1.000**、拒答准确率 **82.5%**、平均 tokens **1929.7**、平均回答延迟 **12901ms**、总费用 **¥0.088384**。
- 实测偏差：① 首次重跑命中 S3-7 QA 缓存（tokens=0/费用=0），清空 `qa:v1:*` 后重跑，报告采用清缓存结果；② 在线客户端原先把 `meta` 全部上下文当引用，引用精确率 0.228，改为只统计正文 `[n]` 后 0.897；③ 7 条应拒题走 chitchat 分支，回复内容上拒绝但不置 `refused`，自动拒答 82.5%（人工语义 10/10），已在 EVAL_M2 说明，不粉饰成 100%。
- 文档同步：API.md（`retrieval`/`cost_yuan`）、EVAL_M2、DECISIONS D-043、PROGRESS、实施计划 S3-9 勾选、spec/plan 实施记录；无 SCHEMA/迁移/新依赖。
- 已知不足：40 条样本与 37 块语料统计意义有限；q028 的“未使用 [2]–[6]”被正则误计为引用；q014 题面本身有歧义；chitchat 拒绝与 RAG 拒答语义未统一；未自动打 `m2-rag-done` tag，未 push。

### 2026-11-02（S3-8）
- S3-8 完成（按 §10 全流程：spec `docs/spec/s3-8-qa-chat.md` + plan `docs/plan/s3-8-qa-chat.md`，均经用户确认）。交付：4 个会话接口（列表/回放/PATCH/DELETE）与 `QaConversationOut/QaHistory*` schemas；前端 `types/qa.ts`、`api/qa.ts`、`utils/{sse,typewriter,highlight}.ts`、`components/qa/{CitationCard,ChatMessage}.vue`、`views/qa/{scope.ts,Chat.vue}`、`views/notes/NoteReadView.vue`；`/qa` 与 `/notes/:id` 路由。
- 拍板（D-042）：会话列表是有界最近列表（`limit` 1–100 默认 50），在 AGENTS §9.2 记录为分页例外；历史引用左连接 notes/note_chunks，缺失 `note_available=false`；历史拒答只按正文精确匹配；引用高亮在 `on-html-changed` 后 80ms 去抖，并支持“去公式”候选匹配。
- 测试：后端新增 16 条（service 7 + API 9），基线 719 → **735 passed, 1 warning**；前端新增 29 条/9 文件，基线 85/20 → **114 passed / 29 files**；`npm run build` 退出 0（仅 775KB chunk 警告）。
- 真实 10 轮 SSE（真实 Postgres + Redis + DashScope `qwen-plus`，`test1` id=18）：总耗时 **93.7s**、done tokens **22,092**；首字 1.590–34.627s；第 1 轮缓存命中 **248ms/tokens=0**，第 5 轮拒答 **2.868s/30 字/refused=true**，第 9 轮 chitchat **1.599s/0 citations**；10 轮共 20 条消息、30 条引用、1 条拒答。
- 真实接口：列表 22 条，首条 20 条消息；改名 200「S3-8 验收会话」；临时会话删除 204、再查 404/40400。
- 真实浏览器（Chrome headless + CDP，`localhost:5173`）：引用点击落 `/notes/55?...&chunk=255`，`mark.citation-hit` 命中标题/正文且无回退；含公式的 note 49 落 `/notes/49?...&heading=单调性`，命中「单调性 + 定义：…」且正文未丢；刷新 `/qa?conversation=22` 恢复 22 条消息/32 条引用/1 条拒答；UI 新建→改名→删除临时会话成功；教师访问 `/qa` 落 `/403`。
- 实测抓修（偏差，已写入 D-042）：① 公式片段原文本无法在 KaTeX DOM 命中，`highlightSnippet` 改为完整→去公式→非公式行的候选匹配，并补块级分隔；② 预览未渲染完就标注会导致段落丢失，改为 `on-html-changed` 后 80ms 去抖 + `appliedQuery/applying` 防重入；③ 测试 PreviewStub 改为在 mounted 时触发 `onHtmlChanged`，与真实组件事件路径一致。
- 已知不足（不粉饰）：会话列表固定 50 条无分页；历史拒答 reason/suggestions 不恢复；引用高亮仍是文本匹配，公式/强排版可能退化为章节定位；删除会话物理级联不可恢复；未引 E2E 依赖，本轮用本机 Chrome CDP，CI 无浏览器自动化。

### 2026-11-02（S3-7）
- S3-7 完成（spec `docs/spec/s3-7-cache-llm-logs-usage.md` + plan `docs/plan/s3-7-cache-llm-logs-usage.md`，用户确认后内联执行）。交付：迁移 `0008_s3_7` 与 `models/llm_call_log.py`；`core/cache.py`（Redis/Memory/Null，fail-open）；`services/qa_cache_service.py`；`ai/embedding/cached.py`；`core/llm_log.py`；`ai/llm`/`ai/embedding` 适配器埋点；`services/usage_service.py`、`schemas/usage.py`、`GET /api/v1/admin/usage`；`qa_service` 缓存命中/写回与 `done.cached`；`scripts/cache_eval.py`
- 拍板（D-041）：QA 缓存 key=(user, 规范化问题, scope) 且不含历史；命中仍落新消息与引用、`tokens=0`；Embedding 只编码 miss；调用日志 best-effort 独立 Session；成本按配置单价；用量按 UTC 日 × scene × model；scene 扩展 `query_rewrite/kp_align` 等；rerank 暂不落库
- 测试：新增 33 条（模型 4、缓存 7、Embedding 缓存 4、调用日志/适配器 10、用量 5、QA 缓存流程 3），基线 686 → **719 passed, 1 warning**
- 迁移：真实 Postgres `alembic upgrade head` 成功（`0007_s3_5 → 0008_s3_7`）；`cost NUMERIC(14,8)`、`user_id ON DELETE SET NULL`、scene/status CHECK、3 个索引
- 验收（真实 Postgres + Redis + DashScope，`test1` id=18，2026-11-02）：`scripts/cache_eval.py --user-id 18` 最终一轮第一问 36.468s、`cached=false`、`tokens=4251`、新增 4 条调用日志、Redis 已写入；第二问 **0.014s**、`cached=true`、`tokens=0`、**新增 0 条调用日志**、答案一致且落新消息
- 真实 `GET /api/v1/admin/usage?range=7d`（临时 admin token，用后删除账号）：200；累计 `totals.calls=8`、`prompt_tokens=5386`、`completion_tokens=3047`、`total_tokens=8433`、`cost_yuan=0.010392`、`avg_latency_ms=8730.88`；items 为 embed/qa/query_rewrite 三组
- 与 plan 的偏差：实际新增 33 条（plan 估 27），全量 719 而非 713；缓存层单测 4 条而非 3；`_chat_stream_impl` 拆出包装器以便在生成器关闭时补记 failed；`align` 测试 Fake 补 `scene` 形参
- 已知不足（不粉饰）：缓存 key 不含历史，指代追问可能命中旧答案；缓存不按 Prompt/模型版本失效；Redis 故障时最多多 0.5s 超时；失败调用无 usage 仍记 NULL；未做 429 限流；query_rewrite LRU 未迁移

### 2026-11-01（S3-6）
- S3-6 完成（spec `docs/spec/s3-6-citation-check.md` + plan `docs/plan/s3-6-citation-check.md`，用户确认后内联执行）。交付：`services/citation_checker.py`；`qa_service` 校验/重试/标注/聚合 token/cancel_event；`api/v1/qa.py` 断连取消；`schemas/qa.py` done 新字段；`scripts/citation_eval.py`
- 拍板（D-040）：完整生成并校验后再按块发 delta；块级检查，只给未引用块加 `【以下为模型补充，未在你的资料中找到依据】`；两轮无合法引用才拒答；`done` 增加 `refusal_reason/suggestions`；只接 SSE，`answer_question` 保持 S1-6 行为
- 测试：新增 20 条（checker 12、answerer 1、service 5、API 2），全量 **686 passed, 1 warning**
- 验收（真实 Postgres + DashScope，`test1` id=18）：`scripts/citation_eval.py --user-id 18` **10/10 通过**；5 条无依据全拒答（3 `low_score`、2 `no_valid_citation`），5 条部分覆盖全部保留并带补充前缀
- 真实 SSE（错位相减法步骤+历史）：`meta` 3.10s、首个 `delta` 15.06s、4 个 delta、`done` 15.10s；`tokens=2759`、`latency_ms=14672`；DB 消息 32 共 425 字、补充前缀 2 处、citations rank 1–3
- 文档同步：API.md §5、DECISIONS D-040、PROGRESS、实施计划 S3-6 勾选、spec/plan 实施记录；无 SCHEMA/迁移/依赖变化

### 2026-10-31（S3-5）
- S3-5 完成（spec `docs/spec/s3-5-qa-sse.md` + plan `docs/plan/s3-5-qa-sse.md`，用户确认后内联执行）。交付：`models/conversation.py`、`models/message.py`、`models/message_citation.py`、迁移 `0007_s3_5`、`ai/llm` 的 `chat_stream`、answerer 的 `prepare_answer/stream_answer`、`schemas/qa.py`、`services/qa_service.py`、`api/v1/qa.py`
- 拍板（D-039）：真实 token 流；先落 user 再流式，正常结束落 assistant + citations；断连保留 user、不落 assistant；`conversation_id` 对外字符串、库内 BIGINT；流中错误发 `error` 后关闭；本轮不做引用校验与限流
- 测试：新增 30 条（模型 3、LLM 流 5、answerer 3、service 13、API 6），全量 **666 passed, 1 warning**
- 验收（真实 Postgres + DashScope，`test1` id=18）：首问 SSE **meta 1 / delta 181 / done 1**，curl 总耗时 **24.480s**，`done.tokens=1949`、`latency_ms=24472`；DB `messages` user/assistant 两行、`message_citations` 4 行（rank 1–4）、`prompt_version=qa/v1`
- 验收：同会话追问（conversation_id=1）HTTP 总耗时 **3.688s**，新增 user/assistant，引用接口返回 1 条；chitchat `你好` **1.224s**、无 prompt_version；`conversation_id=999` → **404/40400**
- 断连：`curl --max-time 3` 收到 meta + 20 个 delta 后超时（2776 bytes），DB 该轮只有 user、无 assistant；日志出现 `qa_stream_disconnected`，上游未写完成日志，连接已关闭
- 断连修复：同步生成器在 uvicorn 取消时不会主动关闭上游；`api/v1/qa.py` 改为 async SSE 生成器 + `run_in_threadpool(next, ...)` + `finally: events.close()`，复测断开后立即出现 `qa_stream_disconnected`，不再落 assistant
- 文档同步：API.md §5、SCHEMA.md §7、DECISIONS D-039、PROGRESS、实施计划 S3-5 勾选、deploy/README Nginx SSE；spec/plan 执行记录

### 2026-10-31（S3-4）
- S3-4 完成（spec `docs/spec/s3-4-prompt-management.md` + plan `docs/plan/s3-4-prompt-management.md`，用户确认后内联执行）。交付：`models/prompt_template.py`、迁移 `0006_s3_4` + `qa/v1` 种子、`services/prompt_service.py`、`schemas/prompt.py`、`api/v1/admin.py` 三个接口、`render_prompt_text`、`answer_question(prompt_template=...)`、`scripts/ask.py` 读库并打印版本
- 拍板（D-038）：版本行不可变、只增不改；部分唯一索引保证每 name 一个 active；生产只读库、无 active 抛错；只迁 QA Prompt；上下文组装沿用 S1-6；无新依赖
- 测试：新增 26 条（模型 2、渲染/answerer 4、service 12、API 8），全量 **636 passed, 1 warning**
- 验收：迁移后 `qa/v1` active；基线 `ask.py --user-id 18 "错位相减法怎么用"` → `Prompt：qa/v1`；真实 HTTP 建并启用 `qa/v2`（加标记）→ 回答出现【PROMPT-V2】、`Prompt：qa/v2`；`PUT` 切回 v1 → 标记消失、`Prompt：qa/v1`；历史 v1 active / v2 inactive；临时 admin 清理，v2 留历史
- 修复：首次激活触发部分唯一索引冲突，改为“先全部停用 → flush → 启用目标”（`fix(s3-4)`，带 FakeSession 回归断言）
- 文档同步：API.md §11、SCHEMA.md §8.3、DECISIONS D-038、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-4 勾选、spec/plan 执行记录

### 2026-10-31（S3-3）
- S3-3 完成（spec `docs/spec/s3-3-query-rewrite.md` + plan `docs/plan/s3-3-query-rewrite.md`，用户确认后内联执行）。交付：`ai/prompts/rewrite_v1.md`、`ai/rag/query_rewriter.py`（严格 JSON + 2 次重试 + `RewriteOutput` 校验）、`services/query_rewrite.py`（历史裁剪/LRU+TTL/降级）、`scripts/rewrite_eval.py`；`ai/llm/{base,openai_compat}.py` 增加可选 `scene`；新增 6 个 `QUERY_REWRITE_*` 配置
- 拍板（D-037）：4 类意图只做流程分支，chitchat 同一次调用生成 reply 且不检索；history 由调用方传入、最近 3 个 user 轮、单条 300 字；缓存进程内 LRU/TTL、只缓存成功；LLM 失败回退原问题 + `note_query` + `degraded=True`，不中断检索；不加接口/表/迁移/依赖
- 测试：新增 24 条（AI 10、service 13、llm scene 1），全量 **610 passed, 1 warning**
- 验收：`scripts/rewrite_eval.py --user-id 18 --top-k 3` → hit@3 **9/10**、degraded 0/10、tokens 3958、cost ¥0.003802、PASS；闲聊与独立问题检查通过；失败条为检索未召回 `note 77/chunk 11`，未改样本/关键词
- 文档同步：DECISIONS D-037、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-3 勾选、spec §9/§11、plan 执行记录；无 API/SCHEMA/前端改动

### 2026-10-31（S3-2）
- S3-2 完成（spec `docs/spec/s3-2-retrieval-service.md` + plan `docs/plan/s3-2-retrieval-service.md`，用户确认后内联执行）。交付：`ai/rag/retriever.py` scope 下推（join `notes`，恒带 `user_id` + `deleted_at IS NULL`）与 `embedding_ms`、`schemas/retrieval.py`、`services/retrieval_service.py`、`api/v1/retrieval.py`（`POST /api/v1/retrieval/search`，student）、`scripts/retrieval_bench.py`；新增 3 个配置项 `RETRIEVAL_TOP_K/RECALL_K/RERANK_ENABLED`
- 拍板（D-036）：scope=`{subject_id?,folder?,start_date?,end_date?,chunk_types?}`（`notebook_id` 改为 `folder`，无 notebook 表）；日期按 `created_at`、end 含当天；rerank 可请求覆盖、debug 默认关；SQL 只在 retriever，service 只编排；空库 200+空 hits；P95 HTTP 端到端、rerank=false、含查询 Embedding
- 验收证据：pytest **586 passed, 1 warning**（基线 564 −1 旧拒参用例 +4 retriever +10 service +9 API）；前端未改
- 真实联调（真实 Postgres/Embedding/Rerank）：验收笔记 81（subject=7/folder=函数）2 块（note+question）；无 scope/subject7/folder=函数/当天各 2 命中，subject8/folder=数列/创建前/题型 formula 各 0；`chunk_types=["question"]` 只 1 条 question；`rerank=true` 走 `qwen3-rerank`、fallback=否、candidates=2、latency=193ms、scores=0.832/0.528；debug 返回 vector/fulltext/fused 各 2 条、`embedding_ms=148`；空库学生 200+0 命中；匿名 401/40100、teacher 403/40300
- 性能：`retrieval_bench.py --runs 20 --warmup 3 --no-rerank` → wall P50=172ms / **P95=229ms**（server P50=163/P95=223，embedding P50=154ms），达标 <500ms
- 回归：`ask.py --user-id 28` 回答引用笔记 #81 两块（refused=否、llm_calls=1、cost ¥0.001431）；`retrieval_eval.py --user-id 28` 10 问正常跑完（仅 1 篇笔记，hit@5=2/10，rerank fallback=0/10）
- 文档同步：API.md §5（检索接口 + qa scope 改 folder）、SCHEMA.md §4.3、DECISIONS D-036、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-2 勾选、spec/plan 执行记录；无迁移、无新依赖、无前端改动
- 已知不足：见遗留 53–57；subject 过滤不命中文档笔记、folder 无 notebook 语义、P95 受外部 Embedding 支配、debug 体积大、kp 过滤未做

### 2026-10-31（S3-1）
- S3-1 完成（spec `docs/spec/s3-1-index-service.md` + plan `docs/plan/s3-1-index-service.md`，用户确认后实施）。交付：`ai/parse/markdown.py`（笔记 Markdown → `ParsedBlock`）、`services/index_service.py`（`build_note_chunks` / `index_note` / `delete_note_chunks` / `purge_deleted_note_chunks` / `start_rebuild` / `get_rebuild_progress`）、`schemas/indexing.py`、`tasks/index_note.py`、`api/v1/admin.py`；笔记创建/正文更新 best-effort 入队 `index.note`，软删同事务清切片
- 拍板（D-035，2026-10-31 用户确认）：每笔记一个任务 + `run_id` 聚合进度（不建表/不迁移）；索引全部未删除笔记（含 3 篇文档笔记）；全量重建按 Markdown 重建、文档笔记页码归零；软删清理切片；队列故障不影响保存；重建入队失败 500；不加锁靠 runner 重试；只有 `content_md` 变化触发重索引
- 验收证据：pytest **564 passed, 1 warning**（基线 524 + 40：Markdown 12、service 11、task 4、admin 8、notes 4、并发用量回归 1）；前端未改（85 passed 基线）
- 真实联调（真实 Postgres/Redis/MinIO + ARQ Worker + DashScope Embedding）：建 note 79 → `index.note` succeeded 2 块/58 tokens，`heading_path=函数`、`函数/单调性`；PATCH 追加唯一标记 → 新任务 succeeded、命中 1 行、块数 2、重复分组 0；软删临时笔记 → 残留 0、孤儿 0；全量重建两次均 `percent=100 / succeeded=5 / failed=0 / chunks=39`，表内 39 行、重复分组 0（各笔记 2/6/8/21/2），重建后 `page_no` 非空 = 0（确认代价）；student 重建/进度 403、匿名 401、坏 run_id 422、未知 run 404；`scripts/ask.py --user-id 25` 真实回答并引用笔记 #79「函数/单调性」片段（refused=否，llm_calls=1）
- 实测说明：重建 run 1 `purged_chunks=0`（库内当时无软删残留）；`chunks=39` 与表内行数一致，证明按 `run_id` 聚合的块数与库一致
- 实测抓修（`976216e`）：并发重建时 S1-3 用共享 `EmbeddingClient.usage_tokens` 差值统计，任务间互相串账（note 79 单建 58 tokens，重建时被记成 662 = 588+74；第二轮 144 = 74+70）。改为累加本次 `on_batch` 的 `BatchStats.tokens`，新增并发回归测试；修复后重建 4 篇笔记 tokens=70/588/437/1168（note 77 三批 611+429+128），全量 **564 passed**
- 清理：验收账号 2 个、笔记 3 篇（含软删）、异步任务 18 条全部删除；修复验收账号 1 个与 4 条任务删除；库回到 4 篇未删除笔记 / 37 块（3 篇文档笔记 35 + 原手写笔记 2），本次重建已使 `page_no` 归零
- 文档同步：API.md §2/§11、SCHEMA.md §4.3、DECISIONS D-035、PROGRESS、AGENTS §9.2/§9.6、实施计划 S3-1 勾选、spec/plan 执行记录；无迁移、无新依赖、无前端改动
- 已知不足：见遗留 49–52；全量重建丢页码、无单笔记重跑、并发唯一键冲突靠重试、无增量重建

### 2026-10-29（S2-13）
- S2-13 完成（spec `docs/spec/s2-13-files-ui.md` + plan `docs/plan/s2-13-files-ui.md`，用户确认后实施）。交付：后端 `File.chunk_count`、`FileSummaryOut`/`ChunkPreviewOut`、`GET /files`、`GET /files/{id}/chunks`，`parse-status` 增 `chunk_count`；前端 `types/files.ts`、`api/files.ts`、`views/files/{constants,useFileUploads,FileListView}`、`components/files/FileUploader.vue`，`/files` 路由替换占位页
- 拍板（D-033，2026-10-29 用户确认）：文件历史用持久后端列表；切片显示块数 + 前 3 条；失败重试由前端重传原始 `File`（不做服务端重试接口）；文件页只收文档类型；列表固定 `created_at DESC, id DESC`；轮询 3s、单文件上限 5min；上传串行
- 验收证据：pytest **512 passed, 1 warning**（基线 506 + 6 条列表/块数/切片契约）；Vitest **56 passed / 14 files**（新增 17：常量 4、队列 5、上传组件 2、列表 6）；`npm run build` 通过
- 真实联调（Chrome 155 + CDP，1440×900，真实 Postgres/Redis/MinIO/ARQ Worker，`PARSE_FORCE_PYMUPDF=true` 加速 PDF）：注册 `s213_e2e_88038676` → `/files` 选择 7.8KB、6 页 ASCII 试卷 PDF → 上传 → **完成 · 7 块**；API `GET /files` 返回 `id=11, done, 100, chunk_count=7`；刷新后列表仍在且仍为 7 块；切片抽屉显示 #1–#3（9/79/78 tokens）；重新选 `.png` 被前端拒绝（“仅支持 PDF…”）且不发请求；console error 0、exception 0；1440 视口 `scrollWidth=innerWidth=1440`
- 实测抓修：① 列表页测试给 `teleport` 打 stub 导致 Element Plus `ElSelect` 递归更新（9–12 个 unhandled errors），去掉 stub 并等待抽屉渲染后消失；② 首次 E2E 脚本按错误文件名断言，实际文件名为 `tmp-s213-paper.pdf`，重跑新账号完成（产品无问题）；③ 824px 窄视口横向溢出来自全局 `body min-width:1024px`，1440px 正常，记为遗留 48
- 清理：两个验收账号（id 20/21）、2 个文件、2 篇文档笔记、14 条切片、4 条异步任务、2 个 MinIO 对象全部删除，计数回 0；临时 PDF/PNG/截图/CDP 脚本/Chrome profile 删除
- 文档同步：API.md §3 + §12、DECISIONS D-033、PROGRESS、实施计划 S2-13 勾选、spec §10、plan 执行记录；SCHEMA 无变更（`chunk_count` 为只读派生属性）
- 已知不足：见遗留 42–48；文档类型限制、无删除/下载、失败仅当前会话可重试、只预览 3 条、队列不跨刷新、轮询 5min 上限、S2-10 英文长 evidence 对齐失败、<1024 全局横向滚动

### 2026-10-27（S2-12）
- S2-12 完成（spec `docs/spec/s2-12-notes-ui.md` + plan `docs/plan/s2-12-notes-ui.md`，用户确认后实施）。交付：`views/notes/{NoteListView,NoteEditView,useNoteList,useNoteEditor,listQuery}`、`components/notes/{TagInput,MarkdownEditor}`、`api/{notes,files,kp}.ts`、`types/{notes,files,common,kp}.ts`、`utils/{noteDraft,noteImages}.ts`；路由 `/notes`、`/notes/new`、`/notes/:id/edit` 与 `meta.nav` 侧栏/面包屑高亮；后端 `POST /files?parse=false` 与 `GET /files/{id}/image`
- 拍板（D-032，2026-10-27 用户确认）：表格列表、直接编辑页、本地草稿 + 手动保存、`md-editor-v3` + KaTeX 懒加载、图片 `note-file://<id>` + Bearer blob 预览、`parse=false` + 鉴权取图接口、关键词/学科/排序/分页筛选；不引入 base64 图片、不做服务端自动保存
- 验收证据：前端 `npm run test:run` **39 passed / 10 files**；`npm run build` 通过（编辑页 chunk 405 KB / gzip 140 KB）；后端 pytest **506 passed**（基线 500 + 6 条图片契约）
- 真实联调（Chrome 155 headless + CDP，1440×900，真实 Postgres/Redis/MinIO）：注册 `s212_e2e_*` → 新建笔记（标题+正文+块级公式）→ 工具栏“上传图片”选 64×64 PNG → 预览 `.katex=1`、`img.naturalWidth=64`；保存 URL 变 `/notes/37/edit`；DB `content_md` 含 `note-file://8`，不含 MinIO endpoint/`X-Amz`；刷新后标题/公式/图片仍在（blob 重新换取，`naturalWidth=64`）；改标题 1.3s 后草稿写入 localStorage，侧栏离开弹确认，取消内容仍在，再离开回列表；重开弹“恢复草稿”，恢复后标题为草稿值，保存后草稿 key 删除；列表 12 条默认 10/页、翻页 2 条、20/页 12 条、关键词 1 条、学科筛选 6 条、标题排序、删除确认后 11 条；图片接口实测 200 + `image/png`/ETag/nosniff/private max-age=300；console error 0；`scrollWidth=innerWidth=1418`
- 实测抓修：① 新建保存后 `onCreated` 在 `saving=true` 时触发路由，被 `onBeforeRouteLeave` 误拦（单测发现），改为 `finally` 中 `saving=false` 后再回调；② 列表时间按 UTC 原样展示，改为浏览器本地时区；③ 新建空白笔记状态显示“已保存”，改为“新笔记”
- 清理：验收笔记 12 篇、文件 1 个、异步任务 13 条、用户 1 个与 MinIO 对象 `uploads/17/...` 全部删除，计数回 0；临时 CDP 脚本与截图不入库
- 文档同步：API.md §3、DECISIONS D-032、PROGRESS、实施计划 S2-12 勾选、spec §15/plan 执行记录；SCHEMA 无变更
- 已知不足：见遗留 37–41；图片 token 导出不通用、取图一次读内存、无压缩、草稿仅本地、无阅读页/文件夹/标签筛选/版本/回收站、编辑包偏大、教师/家长无入口

### 2026-10-27（S2-11）
- S2-11 完成（spec `docs/spec/s2-11-frontend-shell.md` + plan `docs/plan/s2-11-frontend-shell.md`，用户确认后实施）。交付：`styles/tokens.css` + `base.css`（设计 token 与 Element Plus 变量覆盖）、`layouts/MainLayout.vue`、`components/layout/{SideNav,TopBar}.vue`、`components/common/{PageHeader,EmptyState,StatusPage}.vue`、`views/{LoginView,ComingSoonView,ForbiddenView,NotFoundView}.vue`、`router/{index,guard,meta}.ts`、`stores/auth.ts`（token+user+fetchMe）、`api/auth.ts`、`types/auth.ts`、`utils/redirect.ts`；Vitest 配置与 17 条测试
- 拍板（D-031，2026-10-27 用户确认）：桌面优先（1440/248/56/1160）、克制研究工作台视觉、全应用骨架 + 占位页、登录+学生注册、壳+基础组件层、允许新增测试依赖 vitest/@vue/test-utils/jsdom；守卫 fail-closed；注册成功自动登录；401 带 `redirect` 回跳
- 验收证据：`npm run test:run` **17 passed / 5 files**；`npm run build` 零 TS 错误；真实 Chrome 1440×900（CDP）注册 `s211_e2e_*` → 自动登录 `/notes`；刷新后昵称/角色保持；退出后 token 清空；未登录访问 `/notes` → `/login?redirect=/notes`，登录后回 `/notes`；把 token 改坏后刷新 → 401 清 token 回登录；`/not-exist` 404、`/403` 403、`document.title` 正确；布局实测侧栏 248、顶栏 56、内容 1160、左边距 264；主色 `rgb(59,91,219)`；console error 0；验收账号已从库中删除
- 与 plan 的偏差（已记录在 plan 执行记录）：① `VITE_API_BASE` 是 host 而非 `/api/v1`，在 `http.ts` 增 `API_PREFIX`，auth API 走 `/api/v1/auth/*`（否则请求会打到 `/auth/login` 404）；② Vitest 需 `server.deps.inline: ['element-plus']`，否则 async-validator 默认导入退化为非构造函数、表单校验恒 true；③ Node 25 自带 localStorage 抢注 jsdom 实现，测试 setup 用内存实现替代；④ Element Plus 错误态有 100ms 防抖，登录页空表单测试等待 150ms；⑤ 403/404 共用 `StatusPage` 组件（plan 原写两份重复样式），减少重复；⑥ plan 的 MainLayout 测试直接挂载组件时，路由父组件又渲染一次 MainLayout，测试路由父级改为 `<router-view />`
- 已知事项（不粉饰）：6 个模块仍是占位页；教师/家长与学生同导航；无手机/深色模式/i18n/全局搜索；token 存 localStorage；主包 1.0 MB；真实浏览器截图已生成但**尚未经人工目视评审**（结构度量与 DOM 文案已核对），样式细节待用户确认
- 文档同步：spec §13、plan 执行记录、DECISIONS D-031、PROGRESS、`docs/AI协作开发实施计划.md` 勾选 S2-9/S2-11；无后端接口/SCHEMA 变更

### 2026-10-27（S2-10）
- S2-10 完成（spec `docs/spec/s2-10-kp-align.md` + plan `docs/plan/s2-10-kp-align.md`，用户确认后实施）。交付：`app/ai/align/{scoring,extractor}.py` + `ai/prompts/kp_align_v1.md`（固定权重打分、候选内 LLM 抽取、严格 JSON + 2 次重试）、`app/services/kp_align_service.py`（KP 向量补全、top-10 召回、分类落库、待确认列表/确认/忽略）、`app/schemas/kp_align.py`、`app/tasks/kp_align.py`（注册 `kp.align`）、`api/v1/kp.py` 4 个 `/kp/align` 接口、`notes.py` 写后自动入队、`parse_document.py` 解析完成后独立 Session 入队、`data/align_demo_notes.json`（30 条验收笔记）。
- 验收证据：pytest **500 passed, 1 warning**（基线 462 + 新增 38）；真实 30 条笔记（note_id 7–36）→ 30 个 `kp.align` 任务全部 succeeded；`knowledge_points.embedding` 补齐 108/108；`note_kps` 36 行（自动 28 / 待确认 8）；人工核对自动关联 **28/28 正确（100%）**，覆盖 25/30 条笔记；5 条仅有 LLM 命中但分数 <0.55（`matched=1, dropped=10`）未落库；待确认列表 200、批量确认 3 → `manual+confirmed` 3、批量忽略 2 → 删除成功；手动重跑 note 15 成功且 `manual` 行保留；清理后五表计数 0、KP 108。
- 实测抓修：首版重跑时未排除已有 `manual` 行，重复插入 `(15, 118)` 触发 `note_kps_pkey`（任务 3 次失败）→ 修复为候选命中 manual 即跳过，并补单测；commit `2fb9dd1`。
- 文档同步：API.md §4 四接口定稿、SCHEMA.md §4.4 行语义、AGENTS §9.2/§9.3/§9.6、DECISIONS D-030、PROGRESS 30–33、实施计划勾选。

### 2026-10-26（S2-9）
- S2-9 完成（spec `docs/spec/s2-9-kp-tree.md` + plan `docs/plan/s2-9-kp-tree.md`，用户确认后实施）。交付：`app/schemas/kp.py`、`app/services/kp_service.py`（一次查询内存组树、level 推导、移动防环/子树高度、删除三段保护）、`app/services/kp_import.py`（`load_tree_file`/`flatten_tree`/纯函数 `plan_sync`/`import_tree`/`referenced_codes_for`）、`app/api/v1/kp.py` 5 接口、`scripts/import_kp_tree.py`（append/overwrite/dry-run/退出码）、`data/kp_math.json`（108 节点 4 层 11 模块）；`api/router.py` 挂载。
- 验收证据：pytest 462/462；真实 CLI append created=108、level 1/11/68/28、二跑 unchanged=108；tree total=108；student 读 200 / 匿名 401 / student 写 403；teacher 建叶子 201(level4)、PATCH 移动 200(level2)、删根 409、引用删 409、清引用 204；overwrite 修复引用 id→code 映射后 deleted=1、被引用节点 skip 并打印原因；清理后各表 0。
- 文档同步：API.md §4 定稿、SCHEMA.md §3.1 注记、AGENTS §9.2/§9.6、DECISIONS D-029、PROGRESS 27–29/日志、实施计划勾选。

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

### 2026-10-26（S2-6）
- S2-6 完成（按 §10 全流程：spec docs/spec/s2-6-file-upload.md + plan docs/plan/s2-6-file-upload.md，均经用户确认）。交付：backend/app/core/storage.py（`ObjectStorage` 协议 + `MinioStorage` + `get_storage()`）、backend/app/services/file_service.py（文件名清洗、类型/magic 校验、流式上传、去重、补偿）、backend/app/schemas/files.py、backend/app/api/v1/files.py、core/config.py 三个上传配置、exceptions.py 新增 413/41300 与 500/50000 存储异常、requirements.txt（minio 7.2.20 + python-multipart 0.0.32）、.env.example、tests 4 个文件共 46 条
- 拍板（D-026，2026-10-26 用户确认，全部选 A）：新增 minio + python-multipart；首次 201 / 重复 200 + `deduped=true`；白名单 pdf/docx/md/txt/png/jpg/jpeg 且默认 60MB；本卡一并交付 `GET /files/{id}/parse-status`（返回 pending）；对象键 `uploads/{user_id}/{sha256[:2]}/{sha256}{ext}`；不信任客户端 MIME；超限 413/41300；并发唯一冲突不删对象；库失败补偿删对象；parse-status 权限同笔记详情；上传仅 student；存储用协议+适配器
- 验收证据：pytest **368 passed, 1 warning**（基线 322 + 46）；真实 MinIO + Postgres（先用 compose 里的 study-agent-minio，venv 内 minio SDK 直连）：同一 PDF 首次 201（`id=1`、`size=77`、`sha256=68d3dbe2…`、`storage_path=uploads/8/68/<sha256>.pdf`、`pending`），第二次 **200** `deduped=true` 且 `id` 相同；psql `files` 仅 1 行；MinIO `uploads/` 前缀 `object_count 1`（77 字节）；再传 `.md` → 201（`mime=text/markdown`，证明文本类通路）；61MB PDF → **413/41300「文件超过 60MB 上限」** 且 files 行数仍 1、对象数不增；A 查 parse-status → 200 `pending`，B 查 A → **403/40300「无权访问该资源」**；清理后 `files=0, users=0`、`remaining 0`
- 与 plan 的偏差（均为文档/测试细节，已同步 plan 执行记录）：① minio 7.2.20 的 `S3Error` 构造签名为 `(response, code, message, resource, request_id, host_id)`，测试改为关键字构造；② 测试样本 `b"%PDF-1.4\\n"` 实为 9 字节，`size` 断言由 8 改 9；③ 重复上传的 API 测试需用真实 sha256 计算对象键后再播种假存储对象
- 已知事项（不粉饰）：去重需读完整个文件（遗留 14）；无病毒扫描、magic 只验头部（遗留 15）；无列表/下载/删除与签名 URL 接口（遗留 16）；`parse_status` 只有 pending（遗留 17）；不同用户同文件各存一份；补偿删除尽力而为
- 文档同步：API.md（§3 两接口定稿 + §12 文件缺口 + §13 新增 41300）、SCHEMA.md（§4.1 storage_path 键规则 / parse_status 现状）、AGENTS.md（§9.2 上传约定、§9.6 存储与上传锚点）、DECISIONS D-026、PROGRESS、requirements.txt、.env.example、spec/plan 执行记录

### 2026-10-26（S2-7）
- S2-7 完成（按 §10 全流程：spec docs/spec/s2-7-task-framework.md + plan docs/plan/s2-7-task-framework.md，均经用户确认）。交付：迁移 0004 建 `async_tasks`（CHECK + 两个索引）；`app/tasks/{__init__,registry,demo,queue,runner,worker}.py`（注册表、demo.sleep、ARQ 适配器、状态机执行器、WorkerSettings）；`services/task_service.py`（提交先落库再入队、查询权限）；`POST /api/v1/tasks/demo`（202）+ `GET /api/v1/tasks/{id}`；配置 4 项；`TaskQueueUnavailableError`；5 个测试文件共 33 条
- 拍板（D-027，2026-10-26 用户确认，全部选 A）：ARQ 而非 Celery；状态存 DB 表 `async_tasks`；提供 `POST /tasks/demo` 验收端点
- 验收证据：pytest **401 passed, 1 warning**（368 + 33）；真实 Redis 7.4.11 + Worker + Postgres：成功任务 5s —— `pending`（attempts=0）→ `running`（attempts=1、started_at 14:56:32.418）→ `succeeded`（`result={"slept":5}`、finished_at 14:56:37.426，正好 5.0s）；失败任务 —— `attempts=3`、`failed`、error=「第 3 次失败：演示任务按请求失败」，ARQ 日志「retrying job in 2.00s」「retrying job in 4.00s」，started_at 只写一次（14:56:52.044，finished_at 14:57:01.222）；B 查 A 的任务 → **403/40300「无权访问该任务」**；Worker 结构化日志（`on_startup` 配置后）出现 task_started/task_retry/task_failed/task_succeeded，只含 id/name/attempts；清理后 async_tasks=0、users=0
- 与 plan 的偏差（已同步 plan 执行记录）：① 额外新增 `app/tasks/__init__.py`，并在包初始化时 import demo（否则只 import runner 时注册表为空，demo.sleep 被判「未知任务类型」）；② runner 日志 extra 的 `name` 与 `LogRecord.name` 冲突（KeyError），改 `task_name`；③ Worker 首轮验收发现 INFO 日志被根 logger 的 WARNING 吞掉，补 `WorkerSettings.on_startup = setup_logging`（追加提交 `fix(s2-7)`）；④ `REDIS_URL` 由 localhost 改 127.0.0.1（Windows IPv6 超时，实测 ARQ `TimeoutError`），默认值/.env.example/本地 .env 同步
- 已知事项（不粉饰）：Worker 崩溃留 running 行（遗留 18）；无列表/取消/重跑（19）；单队列 + demo 端点（20）；短连接提交（21）；`error` 只留最近一次；结果 JSONB 无大小限制
- 文档同步：API.md（§0 轮询约定、§3.5 两接口、§12 任务缺口）、SCHEMA.md（§4.5 async_tasks、§10.15 状态枚举）、AGENTS.md（§9.2 异步任务约定、§9.6 任务框架锚点）、DECISIONS D-027、PROGRESS、README（日常启动 ③ Worker）、requirements.txt、.env.example、spec/plan 执行记录

### 2026-10-26（S2-8）
- S2-8 完成（按 §10 全流程：spec docs/spec/s2-8-parse-worker.md + plan docs/plan/s2-8-parse-worker.md，均经用户确认）。交付：迁移 0005 给 `files` 加 `parse_progress/error_msg/parse_started_at/parse_finished_at` 与两个 CHECK；`ParseStatus` 枚举；`parse_plain_text` 文本支路；`app/tasks/parse_document.py`（下载→解析→切片→upsert 文档笔记→`index_chunks`→状态回写）；上传接口按状态入队；`FileStatusOut` 增 `parse_progress/error_msg`；4 个测试文件共 24 条（文本 2 + 任务 18 + 接口 4）
- 拍板（D-028，2026-10-26 用户确认，全部选 A）：解析产物落“文档笔记”；仅上传自动入队（不加手动重解析接口）；`parse_result_json` 只存统计
- 验收证据：pytest **425 passed, 1 warning**（401 + 24）；真实 PDF + Worker + MinIO + Postgres + 真实 Embedding：中文 2 页 PDF 上传 201 → `parsing(10) → parsing(50) → done(100)`；`notes` 自动建 `source_file_id=4`、`content_md` 含「单调性/例题」；`note_chunks=2` 与 `parse_result_json.chunks` 一致；重复上传 200 `deduped=true`，任务/chunks 不变；损坏 PDF `failed`、`error_msg=FileDataError...`、attempts=3；`.md` done（chunks=1，真实 Embedding 9 tokens）；`.png` failed +「图片解析暂未支持（待 OCR）」；Worker 日志三类事件只含 file_id/chunks/tokens/error；清理后五张表全 0
- 与 plan 的偏差（已同步 plan 执行记录）：① 解析器在 Windows 上失败时仍持有临时文件句柄，`unlink` 抛 WinError 32 会掩盖原始错误，改为 best-effort 清理 + WARNING（追加 `fix(s2-8)`，多 1 条测试，故总数 425 而非 424）；② 既有 S1-1 测试 `test_facade_unsupported_ext` 用的 `.txt` 现在合法，改用 `.xlsx` 并注明 S2-8 契约变更；③ Docling 首轮加载模型约 3 分钟（182s），二次 90s，仍在 300s 超时内
- 已知事项（不粉饰）：大文件无分页续跑（遗留 22）；图片/扫描件待 OCR（23）；文档笔记与文件无删除联动（24）；重试期间状态抖动（25）；进度为阶段值、Docling 首轮慢（26）；ARQ 控制台日志 `↻` 在 GBK 终端报 UnicodeEncodeError（不影响 JSON 日志与任务）
- 文档同步：API.md（§3 上传副作用 + parse-status 字段/状态机）、SCHEMA.md（§4.1 四列 + §10.2 四值）、AGENTS.md（§9.2 解析约定与 handler commit 例外、§9.6 锚点）、DECISIONS D-028、PROGRESS、实施计划勾选、S1-1 spec ParserName、spec/plan 执行记录


### 2026-10-30（S2-14）
- S2-14 完成（按 §10 全流程：spec `docs/spec/s2-14-kp-ui.md` + plan `docs/plan/s2-14-kp-ui.md`，均经用户确认）。交付：`PUT /api/v1/kp/order`（原子改父+重算 level+源/目标兄弟归一，204）；`PendingAlignOut.note_excerpt`（300 字+省略号）；前端 `types/kp.ts`、`api/kp.ts`、`views/kp/{treeUtils,Tree,PendingAlign,usePendingAlign,KnowledgeView}`、`components/kp/KpNodeDialog.vue`；`/knowledge` 两 tab；教师/管理员默认落点；学生只读；Enter/Backspace 单卡队列。
- 验收证据：pytest **524 passed, 1 warning**（基线 512 + 12）；Vitest **82 passed / 19 files**（基线 56 + 26）；`npm run build` 退出 0。真实 1440×900 浏览器：teacher 登录落 `/knowledge`，新增→改名→跨级拖到「函数」下（DB parent 117/level 3）→删除，搜索与刷新正确；20 条真实待确认连续 Enter，confirm 资源计数 20、DB 20 行 `manual+confirmed`、队列 20→0 无旧卡；Backspace 忽略 1 条计数 1；student 登录落 `/notes`，`/knowledge` 只读、无管理按钮/不可拖拽、待确认空态；关键流程 console error 0，两 tab `scrollWidth=innerWidth=1418` 无横向溢出。
- 实测抓修：Element Plus `dragend` 先移除源节点再 emit，`dragging.parent` 不可靠；改为从 `dropNode` 移动后的 `childNodes` 取目标兄弟全集，补树页测试。修 Element 树类型 `FilterValue`/`TreeNodeData` 对齐。
- 清理：删除 21 条临时笔记、21 条 `note_kps`、2 个临时账号、全部 `S214%` 知识点；临时残留 0，学科 7 仍 108 知识点，原有 3 条笔记/1 个用户保留。
- 已知事项（不粉饰）：搜索只做当前学科前端过滤；无批量确认/撤销/历史/并发冲突提示；根节点锁定仅前端；待确认一次一对；<1024 视口沿用全局横向滚动（遗留 48）；截图未做人工像素级目视，布局结论来自 DOM 断言。
- 文档同步：API.md（§4 排序接口 + 摘要字段）、DECISIONS D-034、PROGRESS、实施计划勾选、spec/plan 执行记录；无迁移/SCHEMA/新依赖。

- 后续补丁（2026-10-30）：教师/管理员点击「笔记」「文件」不再 403/空列表，内容区显示「暂不支持查看 + 前往知识库」；学生页面不变。新增 3 条组件测试，前端 **85 passed / 20 files**，build 0；`teacher_demo` 真实浏览器验证占位与跳转，console error 0。
