# DECISIONS.md — 技术决策记录

> 论文「系统设计-方案选型」章节的草稿。条目格式：背景 / 备选 / 决策 / 理由 / 代价 / 验证。
> 规则：新决策先加条目再动工；推翻旧决策不删除原条目，新增一条并注明替代关系；日期用真实决策日期。

## D-001 后端技术栈：FastAPI（Python）
- 日期：2026-10-15（建档时从方案固化，原决策见方案附录 F-1）
- 背景：毕设需集成 LLM / Embedding / 文档解析等 AI 生态
- 备选：① FastAPI(Python) ② Spring Boot(Java)
- 决策：FastAPI
- 理由：AI 生态不可替代
- 代价：若学院强调 Java 技术栈需重新沟通（Java 主业务 + Python 微服务做 AI 的混合方案为退路）
- 验证：—

## D-002 首版学科：数学
- 日期：2026-10-15（方案附录 F-2）
- 理由：知识点体系最清晰、闭环最容易打通
- 代价：多学科扩展为加分项，首版不做

## D-003 向量库：pgvector 而非 Milvus
- 日期：2026-10-15（方案 5.3 / 实施计划附录 B3）
- 背景：需要同时存储关系数据、全文索引与向量
- 备选：① pgvector ② Milvus ③ Elasticsearch + 向量插件
- 决策：pgvector
- 理由：单库降低部署与运维复杂度；数据量级（<50 万 chunk）下 HNSW 性能足够；过滤条件（user_id/subject_id）可与向量检索下推到同一条 SQL，避免"先粗排再过滤"导致的召回损失
- 代价：超大规模（千万级）下性能不及专用向量库；不支持复杂多路融合算子
- 验证：S1-4 实测 P95 检索延迟 < 120ms（10 万 chunk）

## D-004 图片/试卷识别：多模态大模型 API 而非 PaddleOCR
- 日期：2026-10-15（方案 6.1 / 实施计划附录 B3）
- 背景：需要把学生拍照的数学题识别为可编辑的 LaTeX 文本
- 备选：① 多模态大模型 API（Qwen-VL / GLM-4V / 豆包视觉） ② PaddleOCR + 公式识别模型拼装 ③ 自训模型
- 决策：多模态 API
- 理由：整题识别一步到位，公式直接输出 LaTeX；无需安装 paddlepaddle（规避 Windows 编译与 Python 版本适配问题）；数学公式场景效果优于"文字 OCR + 公式模型"拼装
- 代价：按量付费；数据需出网；超长试卷有 token 上限
- 验证：S4-1 用 20 道真实题目对比，人工统计识别可用率（记录到自测文档）

## D-005 PDF 导出：Playwright 而非 WeasyPrint
- 日期：2026-10-15（方案 TL;DR / 实施计划附录 B3）
- 背景：组好的试卷需导出为可打印的 A4 PDF（含中文与数学公式）
- 备选：① Playwright（浏览器打印） ② WeasyPrint ③ reportlab 手工排版
- 决策：Playwright
- 理由：浏览器内核渲染 HTML/CSS，中文字体与 KaTeX 公式表现与网页一致；WeasyPrint 在 Windows 上依赖 GTK、Docker 镜像中文易缺字
- 代价：镜像需预装 chromium（约 +300MB）；渲染比纯 Python 方案慢
- 验证：S5-3 导出后用 pdfplumber 抽文字确认中文与公式未丢失 + 打印实测

## D-006 Python 版本：3.14（偏离方案锁定的 3.11）
- 日期：2026-10-15（用户拍板）
- 背景：方案锁定 Python 3.11，但本机未安装 3.11（有 3.14 / 3.13 / 3.12）；初始 venv 即 3.14
- 备选：① 安装 3.11 重建 venv（严格遵循方案） ② 改用 3.12 ③ 沿用 3.14
- 决策：**3.14**（沿用现有 .venv，无需重建）——同日被用户推翻，由 D-007 取代
- 理由：本机现有环境即 3.14，免去安装与重建；发布已一年，主流基础库（FastAPI/SQLAlchemy/Pydantic）已跟进
- 代价：偏离方案锁定版本；个别依赖（docling 及其传递依赖）可能尚未适配 3.14
- 回退方案：若 S1-1 安装 docling 等出现兼容问题，改装 3.12 并重建 venv，同时更新本条目与 AGENTS.md
- 验证：S0-5 `pip install -r requirements.txt` 全部可装且 uvicorn 正常起服务；S1-1 安装 docling 通过
- 影响：AGENTS.md §2 与 README 环境要求已同步改为 3.14；docs/ 下的方案、实施计划副本保持原文不改，以本条决策为准

## D-007 Python 版本改回 3.11.9（取代 D-006）
- 日期：2026-10-15（用户拍板，推翻 D-006）
- 背景：D-006 曾决定沿用本机 3.14；同日用户改变主意，回归方案锁定的 3.11
- 决策：安装并使用 **Python 3.11.9**
- 理由：回归方案锁定版本，依赖（docling 等）兼容性最稳
- 版本说明：3.11 分支自 2024-04 起仅安全修复、不再发布 Windows 安装器，3.11.9 是最后一个带官方安装器的版本（后续 3.11.10+ 仅为源码安全更新）；本地开发使用可接受
- 安装记录：python-3.11.9-amd64.exe（python.org 官方包，国际线路慢改走华为云镜像，大小 26,216,840 字节与官方一致）；用户模式安装于 `C:\Users\HEXIAO\AppData\Local\Programs\Python\Python311`，已加入用户 PATH，py 启动器已识别（`py -3.11` 可用）；原有 3.14/3.13/3.12 未受影响
- 验证（2026-10-15）：`.venv` 已用 3.11.9 重建完成（pyvenv.cfg：home = Python311，version = 3.11.9.final.0）
- 影响：AGENTS.md §2 与 README 环境要求已同步回 3.11

## D-008 引入 pytest + httpx 作为测试基础设施
- 日期：2026-10-15（用户在 S0-5 执行计划确认时拍板）
- 背景：AGENTS.md §7.2 要求"新增功能必须配测试"；FastAPI TestClient 硬依赖 httpx
- 备选：① pytest + httpx ② 不配测试（违反 §7.2） ③ unittest + requests
- 决策：pytest 9.1.1 + httpx 0.28.1（随 S0-5 第一批进入 requirements.txt）
- 理由：pytest 是 Python 事实标准；TestClient 不用起服务就能测路由与中间件
- 代价：—（仅开发/测试用途）
- 验证：S0-5 冒烟测试 3/3 通过
- 备注：starlette 发出 DeprecationWarning 提示未来 httpx → httpx2 迁移，暂不处理，观察后续版本再定

## D-009 部署范围：仅本地（不公网、不做局域网演示）

- 日期：2026-10-15（方案附录 F-3 拍板）
- 背景：公网部署需先解决真题/教材数据授权与版权问题；答辩需要可达的演示环境
- 备选：公网 / 局域网 / 仅本地（方案原建议为「本地+局域网」）
- 决策：仅本地
- 理由：零数据授权与版权风险；答辩直接用本机演示，答辩前跑 smoke.py 自检兜底
- 代价：演示绑定本机（录屏 S7-6 作为离线兜底必须认真做）；S7 的 Nginx 仍照常交付但只绑本机，不购云服务器
- 验证：—（非技术决策）

## D-010 Agent 优先级：选做（M5 后）

- 日期：2026-10-15（方案附录 F-4 拍板）
- 备选：必做 / 选做
- 决策：选做——主闭环（问答/错题/组卷）做完再上；按方案 8.4 砍需求顺序，进度紧则降级
- 理由：地基未稳先上 Agent 风险高；S6 排期不变，但降级预案现在就约定，避免后期被动
- 代价：若最终降级砍掉 Agent，论文创新点表述需侧重 RAG 溯源问答与掌握度驱动组卷
- 验证：—（非技术决策）

## D-011 自测使用深度：偶尔使用（低于方案建议档位）

- 日期：2026-10-15（方案附录 F-5 拍板）
- 备选：偶尔用 / 持续自用（每周记录，方案建议）
- 决策：偶尔使用
- 理由：用户按自身情况选择，如实记录
- 代价：论文缺「真实使用数据」素材 → 验证策略主体改为 eval/ 评测集（RAG 检索质量、错题诊断准确性、组卷质量），评测集建设升为关键路径，必须认真做；论文效果章节以可复现评测结果 + 定性自用体验呈现
- 备注：不影响 SCHEMA/API 契约；S7-4「自用试用」仍执行但产出定位为定性反馈
- 验证：—（非技术决策）

## D-012 学校对 AI 辅助编码：允许，无附加要求

- 日期：2026-10-15（方案附录 F-7 拍板；用户已向导师确认）
- 决策：允许 AI 辅助编码，无附加要求
- 影响：维持现有 AI 协作开发流程；周报记录设计/自测工作量保留为自愿动作（方案原建议）
- 验证：—（非技术决策）
- 备注：原「M0 前确认」阻塞解除

## D-013 S1-1 解析层实现决策（spec §4 归档）

- 日期：2026-10-18（S1-1 实现验收后归档；spec 见 docs/spec/s1-1-doc-parse.md）
- 决策 1（Docling 消费结构化对象而非 Markdown 导出）：统一结构需要每块页码（prov），Markdown 序列化会丢页码。实测 docling 2.140：`iterate_items()` 出 `(item, level)` 元组、`prov` 含 `page_no`、噪声 label 有 `page_header/page_footer` 等
- 决策 2（PyMuPDF 兜底 heading_path 恒空）：用字号/加粗猜标题属任务卡禁止的启发式，兜底诚实降级（有页码有文本无层级）。实测对比同一教材页：docling 20 块带层级且滤掉页眉页脚；PyMuPDF 33 块无层级且页眉页脚漏入
- 决策 3（docx page_no=None）：Word 分页由渲染器决定，文件内不存在分页信息，标 None 不造假数（任务卡类型写 int，偏离已在 spec 记录）
- 决策 4（parse_force_pymupdf 显式开关）：.env 配置 + CLI 参数双层，降级可审计可复现
- 已知观察（不修，S1-2 消化）：① docling 结构模型对平级标题可能判成嵌套（样张笔记「二/三」挂到「一」下；修正需字号启发式，禁止；heading_path 在切片器中定位为上下文链）② 样张 ⊆ 丢失经 docling/PyMuPDF 双提取器交叉验证为 PDF 自身 ToUnicode 缺陷（文本层为 \x00），解析器无责；PyMuPDF 兜底路径已加控制符清洗
- 模型下载（换机必读）：HF 直连超时 → 设 `HF_ENDPOINT=https://hf-mirror.com` → 撞 Xet 块存储 401 → **加 `HF_HUB_DISABLE_XET=1`**；模型 342MB 已缓存本机，之后离线可跑
- 验证：pytest 20/20；三份样张 37 项断言 36 过 + 1 项证明为样张自身缺陷（详见 PROGRESS 2026-10-18）

## D-014 RAG 管线实现路线：组件拼装，不引入整体框架

- 日期：2026-10-19（S1-2 动工前拍板）
- 背景：用户质疑「坑太多，能否几行代码调用成熟 RAG」；正面比较了 LangChain / LlamaIndex（十几行跑通）与 Dify / FastGPT / RAGFlow（开箱平台）
- 决策：维持方案既定的**组件拼装**路线（各层用成熟库：Docling / pgvector / tiktoken / jieba / 厂商 API，只自写胶水与论文创新规则）
- 理由：① 创新点（错题诊断 / 知识点对齐 / 掌握度 / 组卷）需要定制检索管线，整体框架的抽象层反而碍事；② 答辩可解释性——每层都能讲清原理与参数，工程章节与创新点立得住；③ 「自写」部分仅几百行胶水 + 特化规则，无重复造轮子（符合 AGENTS §2.1）
- 代价：开发节奏慢于框架路线；环境坑由 AI 协作方承担（S1-1 已踩完最重的一批：docling + HF 镜像 + Xet）
- 备注：若论文需要对照基线，可在评测阶段（S7）补一个 LlamaIndex demo 作 baseline，届时再议
- 验证：—（路线决策，S1-2 起按此执行）

## D-015 S1-2 切片器实现决策（spec §4 归档）

- 日期：2026-10-19（S1-2 实现验收后归档；spec 见 docs/spec/s1-2-chunker.md）
- 决策 1（两阶段管道）：阶段 A 重组成逻辑单元（题目/笔记/公式/表格），阶段 B 尺寸调整。规则解耦、各自可单测；单遍扫描会把「题目完整性」和「尺寸约束」纠缠在一起
- 决策 2（尺寸参数 300/800/60）：300 为软目标下限（越过即在下一边界切）、800 为硬上限、60 为笔记块重叠 token 数；集中定义在 chunker.py 顶部常量，作为论文对照实验的调参变量
- 决策 3（formula 简单密度规则）：中文≤2 + 数学符号+数字占比≥40% + 长度≥10 → formula（宁漏勿错）
- 决策 4（formula 三类豁免，实测驱动）：初版密度规则吃掉题目组件——①纯数值选项行 `A．[-1,3]…`（试卷第 2 题丢选项）②小问行 `（1）f(x)=1/(x^2-4)；`（题 13 小问被单拎）③纯答题线 `________`（每道解答题被拆碎）；选项行/小问行豁免判定，纯答题线在预处理直接丢弃（零检索语义）
- 决策 5（章节号保护）：题号正则加 `(?!\d)`——教材「3.2.1 函数的单调性」「1.5 倍」实测被当题号；题号后紧跟数字即排除
- 决策 6（大题标题自判）：S1-1 实测试卷样张里 Docling 未把「一、选择题」标成 heading（笔记里识别了），`^[一二三四五六七八九十]+[、.．]` 由切片器自判为单元边界，终止题目单元
- 决策 7（标题块前置并入）：块文本 == 下一块 heading_path 末元素（S1-1 结构约定，非字号启发式）→ 标题并入它领的小节，标题领着自己的小节
- 决策 8（tiktoken cl100k_base 近似）：DeepSeek 无公开 tokenizer 库；token_count 只做上下文预算用途，误差可接受；接口收敛在 `_count_tokens` 单点，S1-3 起可换官方 tokenizer。实测 tiktoken 0.14.0，BPE 文件下载顺利（无墙）
- 已知观察（不修）：docling 把「三、解答题（本题共 5 小题，共 90」折成两块且第二条误嵌套成标题层——D-013 已知现象③的延伸，S1-2 不改解析器行为
- 验证：pytest 44/44（S1-1 20 + S1-2 24）；三份真实样张：试卷 23 块（question 17 = 17 题，一题一块；题干+选项+小问+解析全聚齐）、笔记 6 块（层级链完整）、教材页 9 块（例1/例2/练习题各成块），直方图主体 0–300 token 无 >800 块（详见 PROGRESS 2026-10-19）

## D-016 S1-3 Embedding 与入库实现决策（spec §4/§5 归档）

- 日期：2026-10-19（S1-3 实现验收后归档；spec 见 docs/spec/s1-3-embedding.md）
- 决策 1（DashScope text-embedding-v4 + 1024 维）：中文数学文本表现好、OpenAI 兼容、按量便宜（0.0005 元/千 token）；实测输出 1024 与 SCHEMA 一致，迁移按 1024 硬编码
- 决策 2（批大小 10 而非任务卡 32）：厂商硬限制「text-embedding-v4 单次最多 10 行、单行 ≤8192 token」；批大小做成配置（EMBEDDING_BATCH_SIZE），代码不写死
- 决策 3（只建 note_chunks、暂不加 FK）：notes/users/files 属 S2-1；S1-3 用合成 note_id/user_id 完成真实入库验收，S2-1 补外键
- 决策 4（调用日志先结构化、S3-7 入库）：本卡迁移范围不含 llm_call_logs；每次 HTTP 批次落 scene/model/tokens/latency/trace_id，S3-7 建表后切换。临时偏离 AGENTS §5，已获用户确认
- 决策 5（jieba 应用层分词 + to_tsvector('simple')）：与 SCHEMA §9 一致，不用 pg_jieba、不用 bigram；查询侧复用同一 tokenize 函数
- 决策 6（高中数学领域词典）：jieba 默认把「单调性」切成「单调/性」，任务卡验收 SQL `函数 & 单调性` 会查不到；新增 `app/utils/math_dict.txt`（45 个高频词，freq=100000）用 jieba 标准 userdict 机制加载。属于词典调优，不改分词算法
- 决策 7（同步 Embedding 客户端）：任务卡接口为 `encode(list[str])`；CLI/Worker 同步最直接，HTTP 超时与重试可控；后续 API 层需要异步时再包线程池
- 已知观察（环境）：Windows 下 Alembic 首次连接 psycopg 曾出现无响应挂起（多次重试后自行恢复）；env.py 已给 `engine_from_config` 加 `connect_args={"connect_timeout": 5}`，避免迁移命令无限等待
- 验证：pytest 78/78；真实三样张入库 23+6+9=38 块、维度 1024、首轮 1169/588/706 tokens、首轮估算花费合计 ¥0.001231；全文 `函数 & 单调性` 命中 3 行；note 101 幂等复跑后仍 23 块；HNSW/GIN 索引与唯一约束已核对（详见 PROGRESS 2026-10-19）

## D-017 S1-4 混合检索与 RRF 实现决策（spec §8/§10/§14 归档）

- 日期：2026-10-20（S1-4 实现验收后归档；spec 见 docs/spec/s1-4-retrieval.md）
- 决策 1（RRF 只认排名）：`score = Σ 1/(60 + rank_i)`，按 `chunk_id` 去重；不把 cosine distance 与 `ts_rank_cd` 归一化相加（量纲不同，单路高分可能绑架结果）。公式、重叠示例与“rank 不是 score”的反例写入 spec §8 与 `test_retriever.py`。
- 决策 2（全文 OR 语义）：S1-3 的 `build_tsquery()` 保持 `&`（验收 SQL 不变）；S1-4 新增 `build_tsquery_or()`，token 去重后 ` | ` 连接，`ts_rank_cd` 排序。自然问句用 AND 实测 10/10 零命中，OR 才有召回。
- 决策 3（subject_id/kp_ids 延后）：`note_chunks` 无这两列，`notes`/`note_kps` 属 S2-1；S1-4 只下推 `user_id`，传入 subject/kp 时抛 `RetrievalFilterUnavailable`，不静默忽略。
- 决策 4（两路串行）：任务卡“并行”理解为两路都执行；同一 SQLAlchemy `Session` 非线程安全，38 块下串行延迟可忽略，S1-5/S3 再考虑多连接并发。
- 决策 5（无新依赖）：复用 SQLAlchemy/pgvector/jieba/Pydantic；不引入 rerank/整体框架。
- 决策 6（Windows IPv6 修复）：`localhost` 先解析 `::1`，Docker 只发布 IPv4，psycopg 无超时会卡死；`DATABASE_URL` 改 `127.0.0.1` + engine `connect_timeout=5`，`test_db.py` 守卫。
- 验证：pytest 93/93（S1-4 新增 15）；真实 38 块；10 问 vector hit@5=10/10 MRR=0.900、fulltext=9/10 MRR=0.725、hybrid=10/10 MRR=0.933；`--user-id 999` 三路 0/10；RRF 抽查 Q1 `v=1 f=1 → 2/61≈0.03279`、Q3 `v=1 f=5 → 1/61+1/65≈0.03178`。
- 已知不足（不粉饰）：hybrid 仅比纯向量 MRR 高 0.033，未达任务卡“明显更好”；Q6 分段函数从纯向量第 1 掉到混合第 3（全文 OR 的 `f`/`1` 噪声块被抬高）；38 块使 hit@5 饱和。S1-5 用 rerank/查询停用词再评估，本卡不事后调参。
- 备注：评测输出中的学校名已脱敏为“某中学”，不改变排名/分数；无 API/SCHEMA/新依赖改动。

## D-018 S1-5 Rerank 接入决策（spec §5/§7/§15 归档）

- 日期：2026-10-20（S1-5 实现验收后归档；spec 见 docs/spec/s1-5-rerank.md）
- 决策 1（默认模型 qwen3-rerank）：DashScope 新一代文本重排，中文数学短文本可用；原计划的 gte-rerank-v2 已公告 2026-05-30 下线，不把新功能建在下线模型上。北京区价格 0.5 元/百万 token，单条 query/document 上限 4,000 token、单请求最多 500 条、总 token 上限 120,000。
- 决策 2（RRF 全量保留，top30→top6）：`retrieve_hybrid()` 仍返回完整 RRF 列表，S1-4 行为不变；新入口 `retrieve_hybrid_reranked()` 只在展示层取 top30 送重排、返回 top6。`fused` 不截断，避免重排失败时丢掉 S1-4 的完整结果。
- 决策 3（3,600 token 截断）：query 与每条 document 都用 tiktoken `cl100k_base` 截到 3,600；30×3,600+3,600=111,600 < 120,000，留 7% 余量吸收 tokenizer 差异。不沿用 512 的旧假设。
- 决策 4（30s 超时 + 2 次重试 + 失败降级）：429/500/502/503/504 与网络错误重试，4xx 不重试；重试耗尽抛 `RerankError`，由 retriever 回退 `fused[:6]`，`RerankInfo.fallback=True` 并打 `rerank_fallback` 日志。只捕获 `RerankError`，其他异常不吞。
- 决策 5（同步客户端、无新依赖）：复用已有 httpx/tiktoken；批量一次请求发全部候选，不逐条调用；`LocalRerankClient` 只占位、抛错，不生成假分数。Rerank 结果只在内存 `rerank_score`，不写 SCHEMA、不做拒答阈值。
- 验证：pytest 124/124（S1-5 新增 31，含 10 条执行中补的边界回归：Windows 控制台 UTF-8、响应顶层非对象、usage.total_tokens 异常、index 越界、429 Retry-After、4xx 不回显正文、tiktoken 加载失败可降级、非 RerankError 不吞、门面构造失败回退、返回条数不足）；75 块 / 6 note 真实四路：vector 10/10 MRR 0.900、fulltext 9/10 MRR 0.720、hybrid 10/10 MRR 0.920、rerank 10/10 MRR 0.950；fallback 0/10、平均 194ms、10 问总费用 ¥0.015630；用户人工判断 7/10 更相关（Q1/2/3/5/6/7/10），Q4/Q9 更差，Q8 持平。
- 已知不足（不粉饰）：75 块偏小、hit@5 饱和，MRR 仅提升 0.030；Q4 奇偶性/Q9 原点对称的 top5 混入笔记/试卷封面；104–106 为合成样张，论文效果数据需用真实材料重跑。Windows 下 stdout 默认 GBK，样张 `✗` 曾使评测在打印阶段中断，已加 `_configure_stdio()` 强制 UTF-8。
- 备注：评测输出中的真实校名/姓名已替换为“某中学/某老师”，不影响排名与分数；无 API/SCHEMA/新依赖改动。

## D-019 S1-6 带引用回答与拒答实现决策（spec §4/§7/§15 归档）

- 日期：2026-10-20（S1-6 实现验收后归档；spec 见 docs/spec/s1-6-answer.md）
- 决策 1（LLM 选型）：DashScope compatible-mode + `qwen-plus`；沿用 httpx 手写 OpenAI 兼容适配器，不引入 `openai` SDK。原因：项目已有 httpx/Key 回退模式，手写适配器对超时、重试、错误体、费用统计可控；用户已确认。
- 决策 2（Prompt/上下文）：Prompt 存 `ai/prompts/qa_v1.md`，Jinja2 `StrictUndefined` 渲染；上下文按 rerank 分排序、`chunk_id` 去重、4,000 token 预算截断；每条编号 `[n]` 并带 `note_id/source_file_id/page_no/heading_path`。
- 决策 3（引用校验）：非拒答答案必须至少一个引用，所有 `[n]` 必须在 1..本次上下文条数；非法/缺失重试一次（带上次回答+纠正指令），仍非法拒答 `citation_invalid`，不返回不可溯源答案。
- 决策 4（τ=0.45）：原计划 0.35 实测无法分开（应答题 top1 最低 0.4586，应拒题最高 0.4347，“天气”0.3780）；经用户确认改为 0.45。10+5 小样本暂定，完整 20+10 留 S1-7；τ 仍是配置项。
- 决策 5（rerank 回退）：`rerank_info.fallback=True` 或全部 score 为 None 时跳过 τ，继续用 RRF top6，`degraded=True`；不把 rerank 网络失败误判为“资料里没有”。
- 决策 6（语料/引用展示）：note 107 是为任务卡验收问题补的合成数列样张（8 块，全库 83 块/7 note），不是真实学生数据；S2 建表前不显示标题/文件名，只显示现有字段。
- 验证：pytest 160/160；真实 qwen-plus 错位相减回答带 4 条引用、`llm_calls=1`；天气问题 `refused=是`、`llm_calls=0`；证据见 eval/results/s1-6-qa-demo.txt 与 s1-6-refusal-calibration.txt。
- 已知不足（不粉饰）：τ 与应答题最低分只差 0.0086，间隔窄；引用校验只查编号存在性，不判断语义支撑；83 块仍小；无 API/SCHEMA/迁移改动。校准输出中的校名用通用正则脱敏为“某学校”，不在脚本里维护真实校名名单。

## D-020 S1-7 评测集与指标口径（spec §4/§10/§15 归档）

- 日期：2026-10-21（S1-7 实现验收后归档；spec 见 docs/spec/s1-7-eval.md）
- 决策 1（gold 来源）：原计划用户手工勾选，实际采用 **AI 预标注 + 用户确认**；候选清单为 fused top10 + 全量 83 块目录。数据集与论文中必须写明该方式，不得宣称纯人工标注；候选清单参考检索结果会带来选择偏差，`hit@5` 不外推。
- 决策 2（三配置只比检索）：vector/hybrid 只跑检索，不调用 LLM；回答/引用/拒答指标只在生产配置 `hybrid_rerank` 上算，避免三次 LLM 费用和不可比。
- 决策 3（top_n=5，延迟口径）：hit@5/MRR@5 固定 top5；纯向量延迟复用同一次混合检索调用，是保守口径，不是严格隔离的纯向量 SQL 基准。
- 决策 4（重复检索）：`hybrid_rerank` 先独立检索一次算 hit@5，再调 `answer_question()`（内部再检索一次）；因此检索延迟与回答延迟不是同一次调用，成本略高，但避免改 S1-6 answerer 契约。
- 决策 5（数据集/隐私）：`qa_set.jsonl` 只存问题、scope、chunk ID，不存正文、姓名、学校；候选清单含校名/命题人时统一泛化为“某学校/某老师”；不提交 DOCX 与 `.env`。
- 验证：pytest 191/191（新增 31）；真实 vector hit@5=1.000/MRR=0.917、hybrid 1.000/0.827、hybrid_rerank 1.000/0.938、引用精确率 0.827、引用命中率 1.000、拒答准确率 100%、回答平均 6243ms/945.5 tokens/¥0.0317224；证据 eval/results/s1-7-*.json。
- 已知不足（不粉饰）：30 条/83 块，hit@5 饱和且受预标注偏差影响；q004/q005/q009 弱证据；q026/q029 最终拒答正确但已经调用 LLM；引用精确率不等于答案数学正确。

## D-021 S2-1 数据模型与迁移实现决策（spec §2/§3/§5 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-1-data-model.md）
- 决策 1（表数 7 → 5）：任务卡的 `roles` / `user_roles` 在 SCHEMA 中不存在；契约按 `users.role` 单列枚举，API.md 权限与 S2-2/S2-3 任务卡（JWT 含 role、require_role）亦按单角色设计。按 AGENTS §8 以 SCHEMA 为准，不建这两张表，任务卡条目视为 SCHEMA 成文前的旧稿。
- 决策 2（认证路线）：`fastapi-users` 的 SQLAlchemy 适配器 async 专用（官方文档要求 `AsyncSession` + `asyncpg`），且其基础模型要求 `email/hashed_password/is_active/is_verified/is_superuser`，与项目同步 psycopg 栈及 SCHEMA 的 `username/password_hash/...` 冲突；S2-2 改用 FastAPI 官方安全示例（pwdlib/bcrypt + PyJWT），仍不手写哈希与令牌算法。
- 决策 3（枚举 TEXT + CHECK）：PG ENUM 加值不可回滚，`downgrade` 会失效；TEXT + CHECK 可对称 `DROP/ADD CONSTRAINT`，且与 `note_chunks.chunk_type` 的 TEXT 风格一致，中文枚举值（S4 起）也更自然。代价是失去 PG enum 的类型安全，由 Pydantic + CHECK 双层兜底；值集唯一来源 `app/models/enums.py`。
- 决策 4（note_chunks 外键延后 S2-5）：存量 83 行 `user_id=1` 无对应 users 行，S2-1 直接加 FK 会迁移失败；改为 S2-5 建 notes/files 时一起补。SCHEMA §4.3 注记已同步改口径。
- 其他落定：5 张表全部补 `created_at/updated_at`（应用层 `onupdate`，不建触发器）；SCHEMA §0 数组字段定为原生 `TEXT[]/BIGINT[]`（不转 JSONB）；新增 `ck_user_relations_not_self`、`ck_knowledge_edges_not_self` 两条完整性约束与 `ix_user_relations_student_id` 反查索引。
- 验证：pytest 206/206（新增 15）；`alembic upgrade head → downgrade -1 → upgrade head` 往返通过；5 条负向约束（非法 role / 重复 username / 自环边 / 删除被引用学科 / 非法 level）实测均被数据库拒绝且事务回滚无残留；smoke 核心表 6/6。

## D-022 S2-2 认证实现决策（spec §2.3/§10 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-2-auth.md，plan 见 docs/plan/s2-2-auth.md）
- 决策 1（依赖与路线）：哈希用 `pwdlib[argon2]==0.3.1`（Argon2id），令牌用 `PyJWT==2.15.1`（HS256），走 FastAPI 官方安全示例，**不手写哈希/令牌算法**；不用 `passlib`（停更且与 bcrypt≥4 不兼容）、`python-jose`（停更）、`fastapi-users`（D-021 已论证与同步 psycopg 栈冲突）。用户 2026-10-26 批准新增这两个依赖。
- 决策 2（传输与响应壳）：登录走 **JSON**，三条接口都套 `Envelope`；令牌用 `HTTPBearer` 提取。放弃 OAuth2 密码流表单（`OAuth2PasswordRequestForm`）的原因：它会要求登录返回裸 `{access_token,token_type}`，破坏 API.md §0 统一响应，前端也要额外发 form。代价是 Swagger 的 Authorize 不能一键登录，手动粘贴 Bearer token 仍可调试。
- 决策 3（注册角色）：公开注册允许 `student/teacher/parent`，`admin` 用 Pydantic `Literal` 直接 422。老师/家长没有 `user_relations` 绑定就看不到任何学生数据，越权由 S2-3 的 RBAC 与数据隔离兜底，因此不额外收紧。
- 决策 4（令牌生命周期）：单 access token，默认 24h，载荷 `{sub, role, iat, exp}`（`sub` 为字符串 user_id）；不做 refresh/登出/黑名单。无状态 JWT 在过期前无法吊销，密钥轮换会让全部 token 立即失效——该限制写进 PROGRESS 遗留项，后续卡再补。
- 决策 5（防账号枚举 + 防重名）：登录失败统一 401「用户名或密码错误」；用户不存在时也对固定 dummy 哈希跑一次校验（实测存在/不存在两路 0.26–0.29s 无差异）。重名靠 `uq_users_username` + 捕获 `IntegrityError` → 409/40900（先查后插仍有并发竞态，故以 DB 约束为准）。
- 决策 6（用户名归一化与口令强度）：用户名注册/登录都 trim + 转小写，3–50 字符且不含空白（`Alice` 与 `alice` 是同一账号）；口令 8–128 字符，只存 Argon2id 哈希。
- 其他落定：`role` 以数据库为权威（`get_current_user` 按 `sub` 回表），token 内 role 仅用于快速判断；`AUTH_SECRET_KEY` 为空时 `create_app()` 启动即失败，`env=prod` 时长度 <32 直接校验失败；新增 `40900`/`ConflictError` 并同步 API.md §13。
- 验证：pytest **237/237**（新增 31：配置 4 + 安全原语 10 + 服务 6 + 接口 11）；真实 curl：注册 201（`id=4`、`username=test_user_1`、无 `password_hash`）、重复注册 409/40900、`role=admin` 422/42200、登录 token 长度 164、`/auth/me` 200、无 token/错密码/未知用户/过期 token/乱码 token 均 401 且文案符合预期；DB 中 `password_hash` 前缀 `$argon2id$v=19$m=655`；测试用户已删除，`users` 计数 0。
- 已知不足（不粉饰）：无 refresh/登出/吊销与登录限流（暴力破解防护留给部署层或 S3-7 之后）；Argon2id 单次登录约 270ms（含 DB 与网络，本机 curl 实测 0.269–0.277s），是有意付出的安全成本；无邮箱/手机号验证与找回密码（SCHEMA 无 email 字段）。

## D-023 S2-3 RBAC 与数据隔离实现决策（spec §2.3/§7 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-3-rbac.md，plan 见 docs/plan/s2-3-rbac.md）
- 决策 1（验收载体 = 依赖 + pytest，不新增生产接口）：任务卡要求「A 学生的笔记 B 访问返回 403」，但笔记接口要 S2-5 才有、`/admin/usage` 依赖的 `llm_call_logs` 表未建，本卡没有任何可打的真实学生数据端点。因此生产代码只交付 `core/permissions.py`，用测试内临时 FastAPI 应用挂 `/students/{student_id}/notes` 验证；真实 curl 证据推迟到 S2-5 笔记接口落地时补。用户 2026-10-26 确认。
- 决策 2（admin 不绕过）：`require_student_access` 只认「本人」或「已绑定 parent/teacher」；管理员看学生数据必须走 `require_role("admin")` 的专用管理接口。若在此放行 admin，任何普通学生数据接口都会变成管理员的隐式全量读口子，违反最小权限。
- 决策 3（查看方角色限 parent/teacher）：`user_relations.teacher_id` 语义是「查看方」（SCHEMA §2.2），只有 parent/teacher 角色才查绑定关系；学生即使因脏数据出现在 `teacher_id` 也不放行。
- 决策 4（403 不泄露存在性）：越权统一 `403/40300`「无权访问该资源」，「无权限」与「目标不存在」不可区分；404 只留给已授权后的资源缺失。
- 决策 5（依赖而非装饰器）：`require_role` 写成依赖工厂（角色名在工厂阶段校验，拼错立即 `ValueError`）；`require_student_access` 直接作依赖用，`student_id` 由路径注入；service 层用 `ensure_student_access`。装饰器会隐藏参数与返回类型，也不利于 `dependency_overrides`。
- 决策 6（DB 为权威）：角色与绑定关系一律从数据库读（`get_current_user` 回表 + `user_relations` 查询），token 内 `role` 不参与判定；服务层查询必须显式 `WHERE <model>.user_id = <已授权学生>`，该规则写入 API.md §0 与 AGENTS §9.2。
- 验证：pytest **260/260**（基线 237 + 新增 23：单元 13 + 接口 10）；硬验收用例 `test_permissions_api.py::test_b_cannot_read_a_notes_returns_403` PASSED（403 + 40300 +「无权访问该资源」）；其余覆盖本人 200、已绑定家长/老师 200、未绑定家长/老师 403、admin 读学生数据 403、admin 读管理接口 200、学生读管理接口 403、无 token 401、未绑定家长访问不存在学生仍 403（不泄露）。
- 已知不足（不粉饰）：本卡**无 curl 证据**（无生产接口），以 pytest 为验收证据；无家长-学生绑定管理接口（目前只能 SQL 或后续卡建）；无越权审计日志；每个受保护请求多一次 `user_relations` 查询（走 `uq_user_relations_teacher_student`，未加缓存）。

## D-024 S2-4 通用分页与白名单排序决策（spec §2.3/§8 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-4-pagination.md，plan 见 docs/plan/s2-4-pagination.md）
- 决策 1（库选型）：引入 `fastapi-pagination==0.16.1`。任务卡与 API.md 均点名该库；`pip --dry-run` 实测只新增 1 个包，与 FastAPI 0.143.1 / Pydantic 2.14.1 / SQLAlchemy 2.1.5 无冲突。它的价值在 count 查询会剥掉 ORDER BY、limit/offset 由库生成，避免复杂 select 的 count 写错。
- 决策 2（形状适配）：库原生 `Page` 是 `{items,total,page,size,pages}`，与任务卡 `{items,total,page,page_size}` 不一致。做法是只用库执行查询，结果转成自建 `PageData[T]`，再套 `Envelope`；`size`/`pages` 不暴露给前端。
- 决策 3（参数上限）：`page` ≥ 1，`page_size` 1–100（默认 20）。上限防一次拉全库；越界由 FastAPI Query 校验 → `422/42200`。超过末页返回空 items、total 不变，不报错。
- 决策 4（排序白名单）：`apply_sort` 只接受 `{字段名: 列对象}` 映射里的字段，从结构上杜绝 `order_by(f"...{用户输入}")`；非法字段报 `422/42200` 并列出可选字段；`order` 只允许 asc/desc。
- 决策 5（默认排序）：通用件不猜资源语义，`default_sort` 由各接口传入，全局默认方向 `desc`；没有默认排序的接口会拿到原语句，由调用方自己保证稳定排序（避免分页漂移）。
- 决策 6（筛选）：只用各接口显式 query 参数，不做通用 filter DSL（任务卡要求，也便于索引审查）。
- 决策 7（测试）：分页逻辑用 SQLite 内存库真执行（`StaticPool` + `check_same_thread=False`，让 TestClient 线程与夹具共用同一内存库）；不连 PostgreSQL、不发网络请求。SQLite 只验证分页语义，不替代 PostgreSQL 执行计划。
- 验证：pytest **280/280**（基线 260 + 新增 20：单元 12 + 接口 8），`1 warning` 为既有 StarletteDeprecatedWarning。
- 已知不足（不粉饰）：本卡无生产列表接口，**没有 curl 证据**（笔记 S2-5、错题/题目 S4 接入时补）；`total` 依赖 count，大表深分页会变慢，量大后改 keyset/cursor；无多字段排序、无 `pages`/`links`、无 `page_size` 自定义上限；排序白名单需各接口手工维护（漏写只是不支持，不会注入）。

## D-025 S2-5 笔记表与 CRUD 决策（spec §2.3/§10 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-5-notes-crud.md，plan 见 docs/plan/s2-5-notes-crud.md）
- 决策 1（建表范围）：一次建 `files` / `notes` / `note_kps`，并补 `note_chunks` 的 `note_id`/`user_id`/`source_file_id` 三个外键。任务卡把 files 列为 S2-5 产出，SCHEMA §4.3 也明确外键延后到 S2-5，一次补齐避免再开迁移。
- 决策 2（files.sha256 唯一性）：`UNIQUE(user_id, sha256)`（同用户唯一）。多租户下不同用户上传同一份文件互不可见；S2-6 去重逻辑直接按 `(user_id, sha256)` 命中。
- 决策 3（孤儿清理）：迁移补外键前按条件删除 `note_chunks`：`user_id` 不在 users 或 `note_id` 不在 notes。本库 83 行是 S1-3 实验残留（`user_id=1`，users 为空），删除后不可恢复；新库上是 no-op。保留它们只能造假用户/假笔记，等于把脏数据带进正式库。
- 决策 4（更新/删除语义）：PATCH 部分更新（`exclude_unset`，只改传入字段，`content_md` 变则重算 `content_text`）；DELETE 软删置 `deleted_at` 并返回 204。编辑器自动保存只改正文时，PUT 全量容易清空未加载字段。
- 决策 5（权限）：列表仅本人；详情本人或已绑定家长/老师（复用 `ensure_student_access`，admin 不绕过）；创建/修改/删除仅本人且仅 `student` 角色。写操作共享给家长/老师会让“谁改的”不可追溯。
- 决策 6（检索）：`q` 对 `title` + `content_text` 做 ILIKE，转义 `\`/`%`/`_`。中文原词可直接搜、实现简单；jieba + tsvector 依赖 note_chunks 写入链路，留给 S3 检索卡。
- 决策 7（content_text 规则）：冻结代码块 → 去 `$$…$$`/`$…$`/`\(…\)`/`\[…\]` → 链接取文字、图片取 alt → 去 HTML/Markdown 标记 → 还原转义 → 折叠空白。公式符号对关键词检索无意义；代码内容可能是要搜的词。
- 决策 8（学科校验）：写入前 `session.get(Subject, subject_id)`，不存在 → `422/42200`「学科不存在」。不靠 FK 抛 IntegrityError，避免变成 500。
- 决策 9（标签）：`TEXT[]`（SCHEMA 现值）；过滤用 `tags @> ARRAY[tag]`（`postgresql.ARRAY.contains`），可直接命中 `ix_notes_tags_gin`；单标签 ≤30 字、最多 20 个、去重保序。原计划的 `= ANY(tags)` 在 SQLAlchemy 2.1 已弃用，且不易走 GIN。
- 决策 10（列表出参）：列表返回 `NoteSummary`（无正文），详情/创建/更新返回 `NoteOut`（含 `content_md`）。20 条正文可达数 MB，列表页不需要。
- 验证：pytest **322/322**（基线 280 + 新增 42：content_text 11 + 服务 18 + 接口 13）。真实 curl + psql：建 201（`content_text` 落库为「设 则」）→ 列表 total=1（4 个分页字段）→ 详情 200 → **B 读 A 的笔记 403/40300**（补上 S2-3 的真实接口证据）→ q/tag/subject_id 筛选命中 → 非白名单排序 422/42200（message 列可选字段）→ page_size=101 422 → PATCH 后 `updated_at` 从 `14:20:58` 变为 `14:21:23`、`created_at` 不变、`content_text` 重算为「修订后的正文」→ B 改/删均 403 → DELETE 204 → 列表 total=1（另一条未删）、详情 404 → psql 行仍在且 `deleted_at` 非空 → 清理后 notes/users/subjects/chunks 全为 0。
- 已知不足（不粉饰）：`q` 是 ILIKE 子串匹配，大数据量慢且无语义/分词；软删无回收站、行仍占存储；没有“按学生列笔记”的家长视角接口；`note_kps` 只建表未对齐；`files` 有表无上传接口（S2-6），`notes.source_file_id` 暂时只能由后续流水线写；迁移删除的 83 行不恢复。

## D-026 S2-6 文件上传与对象存储决策（spec §3/§12 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-6-file-upload.md，plan 见 docs/plan/s2-6-file-upload.md）
- 决策 1（依赖）：新增 `minio==7.2.20`（官方 SDK，流式 `put_object` + `presigned_get_object`）与 `python-multipart==0.0.32`（FastAPI 解析 multipart 的硬依赖）。用户批准；无版本冲突。
- 决策 2（去重响应）：首次 **201** `deduped=false`，同用户同 `sha256` 重复上传 **200** `deduped=true` + 已有 `file_id`。状态码不撒谎，前端可区分“新建/复用”。
- 决策 3（类型与大小）：`pdf/docx/md/txt/png/jpg/jpeg`，默认上限 60MB；两者都是配置项（`UPLOAD_ALLOWED_EXTENSIONS` / `UPLOAD_MAX_SIZE_MB`）。扩展名白名单 + 文件头 magic 双校验，防改名绕过。
- 决策 4（对象键）：`uploads/{user_id}/{sha256[:2]}/{sha256}{ext}`，内容寻址、天然幂等、无重名与路径穿越；原始文件名只入库做展示。
- 决策 5（不信任客户端）：`mime` 由扩展名映射，不采用请求头 `Content-Type`；文件名清洗（砍路径、去控制字符、截断保留扩展名）。防止 MIME 混淆与路径注入。
- 决策 6（超限状态码）：新增 `413/41300`「文件过大」并登记 API.md §13；比复用 422 语义准确。
- 决策 7（并发冲突）：内容寻址下两个请求写同一对象，唯一键冲突时 **复用赢家、不删对象**（删了会毁掉赢家）。
- 决策 8（失败补偿）：对象已写、库写失败（非唯一冲突）时尽力删除对象后再抛；补偿删除自身失败不掩盖原始异常。
- 决策 9（parse-status 权限）：本人或已绑定家长/老师（`ensure_student_access`），admin 不绕过；与 S2-3/S2-5 一致。
- 决策 10（上传权限）：仅 `student`；文件属于学生个人知识库。
- 决策 11（存储抽象）：`ObjectStorage` 协议 + `MinioStorage`（懒连接/懒建桶）+ `get_storage()` 单例，路由用 `Depends(get_storage)`；SDK 异常统一 `StorageUnavailableError`（500/50000，不泄露 endpoint/凭据）。测试注入假实现，套件零网络。
- 验证：pytest **368/368**（基线 322 + 新增 46：存储 10 + 规则 13 + 服务 13 + 接口 10）。真实 MinIO + Postgres：同一 PDF 首次 **201**（`size=77`、`sha256=68d3dbe2…`、`storage_path=uploads/8/68/<sha256>.pdf`、`parse_status=pending`），第二次 **200/`deduped=true`** 且 `id` 相同；psql 只 1 行，MinIO `uploads/` 前缀对象数 **1**；再次上传 `.md` → 201（文本类型通路可用）；61MB PDF → **413/41300「文件超过 60MB 上限」** 且行数/对象数不增；A 查 `parse-status` → 200 `pending`，B 查 A → **403/40300**；清理后 files/users 与对象数全为 0。
- 已知不足（不粉饰）：去重必须读完整个文件（sha256 全量），不是秒回；只有扩展名 + 头部 magic，不防“合法 PDF 内嵌恶意内容”，docx 只验 ZIP 头；无病毒扫描、无图片重编码、未接上传限流；`parse_status` 只有 `pending`（S2-8 需迁移扩展）；无文件列表/下载/删除接口，`presigned_get_url` 只在存储层；不同用户传同一文件各存一份（按用户隔离的代价）；补偿删除是尽力而为，极端情况仍可能留孤儿对象。

## D-027 S2-7 异步任务框架决策（spec §3/§12 归档）

- 日期：2026-10-26（用户拍板后归档；spec 见 docs/spec/s2-7-task-framework.md，plan 见 docs/plan/s2-7-task-framework.md）
- 决策 1（框架）：用 **ARQ 0.28.0**（符合 AGENTS §2 的 ARQ + APScheduler 选型），不引入 Celery；`redis` 由 arq 解析为 5.3.1 并显式锁定。
- 决策 2（状态存储）：新建 **`async_tasks` 表**（迁移 0004），ARQ 只当执行器。原因：ARQ 结果默认 1 小时过期、无历史、无法按用户鉴权；DB 还能给 S2-8/S2-11 直接查。
- 决策 3（提交顺序）：先落库（pending）再入队；入队失败把行置 `failed` +「任务入队失败」并抛 500/50000，不留永远 pending 的幽灵任务。
- 决策 4（状态机）：`pending → running → succeeded`；可重试失败回 `pending`，第 3 次失败终态 `failed`。轮询方只需认 4 个值。
- 决策 5（重试）：最多 3 次尝试，指数退避 `2s`、`4s`（`task_retry_base_seconds * 2^(try-1)`）；重试决策在 `runner.execute_task`，ARQ 只负责延时投递（`Retry(defer=...)`）。
- 决策 6（执行模型）：处理函数是同步 `(Session, payload) -> dict | None`，Worker 里 `asyncio.to_thread` 执行；处理器不得自行 commit，runner 统一提交，失败先 rollback 再写 failed/pending。
- 决策 7（幂等）：终态任务再次投递直接返回，不重复执行；任务行不存在 → 返回 `missing` 并记 warning，不抛异常避免 ARQ 无意义重试。
- 决策 8（接口）：`POST /api/v1/tasks/demo`（student，202）+ `GET /api/v1/tasks/{id}`（仅创建者，admin 不绕过）。demo 端点只用于验收/联调，`seconds` 1–10、`fail` 可复现失败。
- 决策 9（轮询约定）：写进 API.md §0——提交 202 + id，客户端每 1–2s 轮询，终态即停；本阶段不做 SSE。
- 决策 10（Windows 坑）：`REDIS_URL` 统一 `redis://127.0.0.1:6379/0`（`localhost` 先解析 `::1`，Docker 只发布 IPv4，ARQ 实测直接 `TimeoutError`），与 `core/db.py` 的 Postgres 注释同因；默认值、`.env.example`、本地 `.env` 同步。
- 决策 11（ARQ 0.28 API 限制）：`enqueue_job` 没有 `_max_tries`/`_job_timeout`（`**kwargs` 会被当函数入参），重试数/超时只能配在 `WorkerSettings`；job id 固定 `task:{id}`。
- 决策 12（Worker 日志）：`WorkerSettings.on_startup` 调 `setup_logging`；否则根 logger 默认 WARNING，`task_started`/`task_succeeded` 等 INFO 会消失（首轮验收实际踩到）。
- 验证：pytest **401/401**（基线 368 + 新增 33）。真实 Redis 7.4.11 + Worker + Postgres：`demo.sleep` 5s 实测 `pending`（attempts=0）→ `running`（attempts=1、started_at 14:56:32）→ `succeeded`（`result={"slept":5}`、finished_at 14:56:37，恰好 5.0s）；`fail=true` 实测 attempts=3、`failed`，ARQ 日志显示 retry 2.00s / 4.00s，started_at 只写一次，error=「第 3 次失败：演示任务按请求失败」；B 查 A 的任务 → **403/40300**；Worker 结构化日志出现 `task_started`/`task_retry`/`task_failed`/`task_succeeded`（只含 id/name/attempts，无 payload 正文）；清理后 async_tasks/users 均 0。
- 已知不足（不粉饰）：`asyncio.run` 每次提交建短连接（低频可用，高频需连接池/后台循环）；单队列、无优先级、无取消/重跑/列表；Worker 崩溃会留下永久 `running` 行（无心跳回收）；`demo.sleep` 是验收入口，前端不应暴露；`error` 只保留最近一次；结果 JSONB 无大小限制。

## D-028 文档解析 Worker 与进度回写（S2-8）

- 背景：S2-6 只把文件落库并置 `pending`，解析与入库未接入；S2-7 已提供任务框架。本卡把上传→解析→切片→向量化串起来。
- 决策 1（产物归属）：解析文本落一条“文档笔记”，`notes.source_file_id = files.id`，chunks 挂其 `note_id`；`note_chunks.note_id` 保持 NOT NULL，不改 S1-3/S1-4 契约。重复解析按 `(user_id, source_file_id)` 复用同一条笔记。
- 决策 2（触发）：仅上传接口入队；新增文件（pending）与失败重试（failed）入队，`done/parsing` 去重命中不重复入队；不新增手动重解析接口。
- 决策 3（结果存储）：`files.parse_result_json` 只存统计（parser/pages/blocks/chunks/tokens/elapsed_ms/degraded_reason/note_id），正文只在 `notes.content_md`，避免大文本存两份。
- 决策 4（状态机）：`pending → parsing → done/failed`；新增 `parse_progress` 阶段值 10/50/80/100，轮询可见；`error_msg` 截断 500 字。
- 决策 5（失败落库）：handler 捕获异常后先 `commit` 文件 `failed/error_msg` 再 `raise`。runner 失败会 rollback，若交给 runner 文件会永远停在 `parsing`；这是 AGENTS §9.2「handler 不得自行 commit」的唯一例外，已回填 §9.2。handler 不提交 `async_tasks` 状态。
- 决策 6（md/txt）：`parse_plain_text` 单 block、`ParserName` 增 `text`；S1-1 的 `ParserName` 说明同步。图片（png/jpg/jpeg）明确 `failed` +「图片解析暂未支持（待 OCR）」，扫描件 `failed` +「扫描版」。
- 决策 7（幂等）：任务重投时 `done` 直接返回 `{"skipped": true}`；重复执行覆盖同笔记 chunks（`index_chunks replace=True`）。
- 决策 8（上传失败语义）：入队失败时文件已落库，接口仍返回 `500/50000`；重新上传命中去重并补入队。
- 决策 9（临时文件）：下载到 `NamedTemporaryFile` 后按原后缀解析；Windows 上解析器可能仍持有句柄，`unlink` 失败只记 WARNING，不掩盖原始解析错误（实测踩到 WinError 32）。
- 验证：pytest **425/425**（基线 401 + 新增 24：文本支路 2 + 任务 18 + 接口 4）。真实 PDF + Worker + MinIO + Postgres + 真实 Embedding：英文/中文样张 `parsing(10) → parsing(50) → done(100)`（Docling 首轮 182s、次轮 90s）；`files.parse_result_json={"pages":2,"blocks":4,"chunks":2,"parser":"docling","tokens":85,...}`；`notes` 一条 `source_file_id=4`、`content_md` 含「单调性/例题」；`note_chunks` 2 条与统计一致；重复上传同一 PDF → 200 `deduped=true`、任务数/chunks 不变；损坏 PDF → `failed`、`error_msg="FileDataError: Failed to open file ..."`、attempts=3；`.md` → `done` 且 chunks=1（真实 Embedding 9 tokens）；`.png` → `failed` +「图片解析暂未支持（待 OCR）」；Worker 日志 `file_parse_started/file_parse_done/file_parse_failed` 只含 file_id/chunks/tokens/error；清理后五张表计数 0。
- 已知不足（不粉饰）：解析+embedding 共用一个 300s job timeout，超大 PDF 可能超时且不能分页续跑；图片/扫描件依赖 OCR 卡；文档笔记会出现在笔记列表，文件无删除接口，笔记与文件可能不同步；重试期间文件状态会在 failed/parsing 间短暂抖动；`parse_progress` 是阶段值而非页级；`parse_result_json` 不含正文，笔记被删后只能重新上传（done 不会重解析）；Docling 首轮加载模型 3 分钟级；ARQ 自带控制台日志含 `↻`，Windows GBK 终端会打印 `UnicodeEncodeError`（不影响任务，JSON 日志正常）。

## D-029 知识点树 CRUD 与导入（S2-9）

- 背景：S2-1 已建 `subjects`/`knowledge_points`/`knowledge_edges`，S2-5 建 `note_kps`，但表为空；S2-9 要交付树读/写接口、导入脚本与种子树。spec 见 `docs/spec/s2-9-kp-tree.md`。
- 决策 1（读权限）：`GET /kp/subjects`、`GET /kp/tree` 登录即可（API.md 原写 student，放宽为登录用户，学生仍可读）；写接口 `require_role("admin", "teacher")`。
- 决策 2（学科入参）：沿用 API.md §4 的 `?subject=math`（学科 code），避免前端先换取 subject_id；出参同时带 `subject.id`。
- 决策 3（组树）：同 subject 全量一次查询（`level, order_no, id`）后内存 `id→node` 组树，禁止按节点递归查库。
- 决策 4（level）：只由父节点推导（根 1、最深 4），创建不接受客户端传 level；父节点必须同 subject。
- 决策 5（移动）：PATCH `parent_id` 时校验非自身/非后代（防环）、目标同 subject、移动后子树高度 ≤4；成功后 BFS 重算全部后代 level。
- 决策 6（code）：创建后不可改；`(subject_id, code)` 冲突先查后捕获 `IntegrityError`，统一 409「知识点编码已存在」。
- 决策 7（删除）：物理删除，业务层三段保护——子节点、`note_kps`、`knowledge_edges`；任一命中 409 并给可读 message，不级联。
- 决策 8（导入模式）：`append` 只按 code upsert；`overwrite` 同步删除文件缺失项。删除按 level 降序；仍有保留子节点或被引用 → 保留并计入 skipped，打印 `skip code=… reason=…`。
- 决策 9（导入引用保护）：先把 `note_kps`/`knowledge_edges` 的 kp_id 映射成 code 再参与计划——首轮实现按 id 与 code 直接比较导致被引用节点仍进入删除集，真实 overwrite 触发 FK 失败（`fk_note_kps_kp_id`），已修复并补 `referenced_codes_for` 单测（commit daad0e5）。
- 决策 10（导入落库）：先按 level 升序建新节点（父先子后，flush 拿 id），再更新、再删除；`--dry-run` 只算计划不落库；数据错误退出 2、DB 错误退出 1。
- 决策 11（subject 自举）：导入脚本按文件 `subject.code` 查 `subjects`，不存在则创建（`math`/`高中数学`/`高中`），S2-9 无需手工造学科。
- 决策 12（种子）：`backend/data/kp_math.json` 108 节点、4 层、11 个二级模块，`code` 形如 `MATH-FUNC-01-01`，`exam_weight` 0.5–1.0 为经验值非考纲；AI 草稿需用户人工校对（本卡交付草稿，不改考纲）。
- 决策 13（接口范围）：不做单点详情、批量移动、拖拽排序、subject 删除、`knowledge_edges` CRUD、embedding 写入；这些留给 S2-10/S2-14/S4-5。
- 决策 14（测试）：`plan_sync`/`flatten_tree` 纯函数单测；service/API 用 FakeSession 按 SQL 文本分派实体，不连库。
- 验证：pytest **462/462**（基线 425 + 新增 37：service 12 + import 12 + seed 3 + API 10）。真实 Postgres + uvicorn + CLI：append `created=108`，`subjects=1`、level 分布 1/11/68/28；二次 append `created=0 unchanged=108`；tree 接口 total=108；student 读 200、匿名 401、student 写 403/40300；teacher 建叶子 201（level=4）、PATCH 移到根下 200（level=2）、删根 409「存在子知识点」、有 `note_kps` 引用删 409「已被笔记引用」、清引用后 204；overwrite `--dry-run` `deleted=2 skipped=0`（修复前）→ 修复后 `deleted=1 skipped=1`，正式执行 deleted=1、被引用节点保留且打印 `skip code=MATH-COUNT-02-02 reason=referenced`，库内 107；再 append 补回 `created=1`；清理后 kp/subjects/notes/users 均 0。
- 已知不足（不粉饰）：种子树是 AI 草稿，需人工校对考点归属与权重；无拖拽/批量排序，`order_no` 冲突不做唯一约束（按 `order_no,id` 稳定排序）；overwrite 直接改库、无自动备份与并发锁（唯一约束兜底，第二个导入会报 409）；append 假设文件是完整树（部分树会把节点 level/parent 按文件重置）；删除物理且无回收站；导入不做跨 subject 批量。

## D-030 笔记/文档 → 知识点对齐与待确认队列（S2-10）

- 背景：S2-9 已导入 108 节点高中数学树、`knowledge_points.embedding` 全为 NULL；S2-5 的 `note_kps` 只有表；S2-10 需实现方案 6.2 的自动对齐 + 待确认队列。spec 见 `docs/spec/s2-10-kp-align.md`。
- 决策 1（触发）：笔记 `POST`/`PATCH` 成功后由路由层 `task_service.create_task` 入队 `kp.align`；入队失败只记 WARNING，不影响笔记保存。手动重跑 `POST /kp/align/notes/{note_id}` 返回 202 + TaskOut。
- 决策 2（文档笔记）：`parse_document` 在文件 `done` 的 commit 之后，用**独立 Session** 入队对齐；异常只记 WARNING，不污染解析 handler 主事务、不把 LLM 延迟塞进解析 job。
- 决策 3（KP 向量）：`ensure_kp_embeddings` 一次查出同 subject `embedding IS NULL` 的节点，按「祖先路径 / 名称 / 描述」批量编码并写回；本次真实补齐 108 节点，后续对齐零成本。
- 决策 4（候选召回）：pgvector 余弦距离取 top-10，按 `note.subject_id` 过滤（为空则全树）；空正文直接 0 关联。
- 决策 5（关键词分）：知识点全名命中 1.0；去掉固定前缀（函数的/数列的/集合的/三角函数的/平面向量的/一元二次/空间的/复数的）后的核心词（≥2 字）命中 0.6；否则 0。
- 决策 6（树先验）：候选任一祖先名出现在笔记 `tags` 或 `title` → 1.0；否则 `level<=2` → 0.3；否则 0。没有“笔记章节”字段，用标签/标题近似“同章节”。
- 决策 7（LLM 角色）：LLM 只从候选 `kp_id` 中选并给 `confidence`/`evidence`；严格 JSON + Pydantic 校验，解析/校验失败最多重试 2 次（共 3 次），仍失败抛 `AlignError` 让任务失败重试；候选外 id/重复 id 丢弃；空候选不调用 LLM。
- 决策 8（分数）：最终分固定 `0.6*cos + 0.3*keyword + 0.1*prior`，LLM `confidence` 只做门槛（`<0.5` 丢弃），不参与加权；`>=0.75` 自动、`[0.55,0.75)` 待确认、`<0.55` 丢弃。
- 决策 9（落库语义）：自动行 `source='ai', confirmed=true`；待确认行 `source='ai', confirmed=false`；确认接口改 `confirmed=true, source='manual'`；忽略删除 `source='ai' AND confirmed=false`。
- 决策 10（重跑）：先删该笔记全部 `source='ai'` 行，保留 `manual`；候选若已有 manual 行则跳过不插入（避免 PK 冲突、不降级用户确认）。真实验收抓到此 bug：首版重跑 note 15 时重复插入 `(15, 118)` 触发 `note_kps_pkey`，已修复并补单测。
- 决策 11（待确认列表）：`select(NoteKp).join(Note)` + `paginate_query`，`AliasPath` 从 ORM 关系展平 `note_title/kp_name/kp_code`；过滤本人、未软删、`source='ai' AND confirmed=false AND confidence∈[0.55,0.75)`；固定排序 `note_id DESC, kp_id`（表无时间列）。
- 决策 12（批量操作）：`confirm`/`reject` 接收 1–100 对，只处理本人笔记；非本人/不存在/状态不符计入 `skipped` 而不 404，保证批量幂等。
- 决策 13（不新增迁移）：`note_kps` 四列 + 现有 `knowledge_points.embedding` 足够；不引入对齐历史表/时间列/审计。
- 决策 14（测试）：新增 38 条（scoring 10、extractor 8、service 8、task 4、api 8）；LLM/Embedding 全部 Fake，pytest 全量 **500 passed, 1 warning**。
- 验证（真实 DashScope Embedding + qwen-plus + Postgres + Redis + ARQ Worker）：注册 `align_student`，30 条验收笔记全部 `POST /notes`（note_id 7–36），30 个 `kp.align` 任务 **succeeded=30 / failed=0**；`knowledge_points.embedding` 补齐 108/108；`note_kps` 36 行 = 自动 28 + 待确认 8。按链接人工核对 28 条自动关联全部与笔记主题一致 → **自动关联精确率 28/28 = 100%**，覆盖 25/30 条笔记；5 条（集合运算/复数/直线与圆/抛物线/导数与单调性）LLM 各命中 1 个候选但最终分 <0.55 被丢弃（`candidates=10, matched=1, auto=0, dropped=10`），属阈值偏严而非错链。待确认队列 `GET` 返回 8 条，批量确认 3 条（15/118、17/155、19/120）→ DB `manual+confirmed=3`，批量忽略 2 条（20/206、26/209）→ 删除成功，剩余待确认 3；`note_kps` 最终 34 行（ai true 28 / ai false 3 / manual true 3）。手动重跑 note 15：任务成功 `auto=1, matched=2, dropped=9`，manual 行保留、ai 行被替换。清理 notes/note_kps/async_tasks/users 后 pytest 复跑 500/500。
- 已知不足（不粉饰）：树先验只是标签/标题近似；关键词无别名表/同义词，召回漏（本次 5/30 完全未关联）；阈值基于 text-embedding-v4 分布，换模型需重校准；LLM 失败即任务失败，无纯算法兜底；待确认无时间列/无审计，忽略后重跑可能再来；文档笔记解析失败则不对齐；并发重跑同一笔记可能 pkey 冲突（任务失败重试）；未写 `llm_call_logs`（S3-7 建表后再接）。

## D-031 前端应用骨架与登录（S2-11）

- 背景：S0-6 只有 `/debug` 验收页；S2-2 的注册/登录/`me` 接口已可用，但没有登录页、布局和守卫；S2-12–S2-14 需要统一视觉与壳。spec 见 `docs/spec/s2-11-frontend-shell.md`。
- 决策 1（设备与视觉）：桌面优先，按 1440 设计；侧栏 248px、顶栏 56px、内容最大 1160px、页面留白 32px；暖白 `#F7F8FA` + 深墨 `#1F2933` + 靛蓝 `#3B5BDB`，1px 分割线、卡片圆角 10px、只保留 1px 阴影，不做后台模板感（用户逐项确认）。
- 决策 2（范围）：一次交付全应用骨架（6 个一级导航 + 顶栏 + 用户区），未完成模块统一 `ComingSoonView` 并标计划任务号；不放假表格/假统计；不做首页仪表盘、手机适配、深色模式、i18n、全局搜索。
- 决策 3（实现方式）：设计 token + `MainLayout` + 基础组件（`PageHeader`/`EmptyState`/`StatusPage`），不引入 Tailwind/新运行时依赖；Element Plus 继续全局注册（S0-6 既有决策）。
- 决策 4（导航）：两位序号 + 文字，不引入 `@element-plus/icons-vue`（非直接依赖）；active 用浅主色底 + 3px 左侧主色条 + `aria-current="page"`。
- 决策 5（登录/注册）：同页自定义文字 tab；学生可自助注册，注册成功自动用同账号登录；校验与 API.md §1 一致（用户名 3–50 无空白、密码 8–128、昵称 ≤50、年级 ≤20）；错误由 `http.ts` 统一 toast，表单只做 loading 与字段校验。
- 决策 6（登录态）：token 持久化 localStorage；user 只存内存，刷新后 `GET /auth/me` 回填；角色以服务端为权威；`fetchMe` 用动态 import 避免 `http → store → api → http` 静态环。
- 决策 7（守卫）：判定抽成纯函数 `resolveAccess({isPublic,hasToken,user,roles,redirectPath})`；`beforeEach` 只负责取数与跳转；要求 roles 但 user 未回填时 **fail-closed 403**；未登录跳 `/login?redirect=<fullPath>`；已登录访问 `/login` 回 `/notes`；403/404 公开。
- 决策 8（安全回跳）：`safeRedirect` 只接受以单个 `/` 开头、不以 `//` 开头、不含反斜杠的站内路径，否则回 `/notes`；401 时清 token 并带当前 `fullPath` 回登录，登录页不重复跳。
- 决策 9（接口前缀）：`VITE_API_BASE` 在开发环境是 host（S0-6 的 `/health` 依赖它），所以 `http.ts` 导出 `API_PREFIX='/api/v1'`，业务 API 显式拼前缀；不在本卡改环境变量语义。
- 决策 10（测试）：经用户确认新增 devDependencies `vitest@4.1.12`、`@vue/test-utils@2.5.1`、`jsdom@29.1.1`，不进入生产包；测试放 `src/**/*.spec.ts` 由 `vue-tsc -b` 一并类型检查；共 17 条（守卫 5、redirect 3、store 3、登录页 3、布局 3）。
- 决策 11（测试环境三坑）：Element Plus 必须 `server.deps.inline`，否则 async-validator 默认导入退化、校验恒 true；Node 25 自带 localStorage 会盖住 jsdom 且无 `clear()`，setup 用内存实现；错误态有 100ms 防抖，断言前等待。
- 验证：`npm run test:run` 17/17；`npm run build` 零 TS 错误；真实 Chrome 1440×900 走通注册→自动登录→刷新保持→退出→未登录 `redirect`→重新登录回跳→伪造 token 401→404/403；布局实测 248/56/1160，主色 `rgb(59,91,219)`，console error 0；验收账号已删除。
- 已知不足（不粉饰）：6 个模块仍占位；教师/家长同学生导航；无手机/深色/i18n/搜索；token localStorage 有 XSS 风险且无 refresh；主包 1.0 MB（gzip 330 KB）；截图尚未人工目视评审，样式细节待用户确认。

## D-032 笔记列表与 Markdown 编辑器（S2-12）

- 背景：S2-5 已有笔记 CRUD、S2-6/8 已有文件上传与解析，但前端 `/notes` 仍是占位页；S2-12 要交付列表、筛选、编辑、公式与图片。spec 见 `docs/spec/s2-12-notes-ui.md`。
- 决策 1（列表形态）：`el-table` 表格而非卡片，列=标题/学科/标签/更新时间/操作；桌面 1440 优先，不做移动卡片降级。
- 决策 2（筛选）：关键词 `q` + 学科 + 排序（最近更新/创建/标题）+ 分页（10/20/50）；URL query 为唯一状态源，`q` 300ms 防抖，筛选变化回第 1 页；后端继续走 S2-4 白名单排序，不新造接口。
- 决策 3（打开方式）：点行/编辑直接进 `/notes/:id/edit`，不做只读阅读页；新建 `/notes/new`；保存后新建页 replace 到编辑页，避免返回栈残留。
- 决策 4（编辑器）：`md-editor-v3@7.1.0` + `katex@0.19.1`，编辑页懒加载；工具栏含标题/列表/代码/表格/图片/KaTeX/预览/保存；`:no-mermaid`，不做 Mermaid；不引 ECharts 等额外依赖。
- 决策 5（草稿）：只做 localStorage 本地草稿 + 手动保存，不做服务端自动保存/每 800ms PATCH（避免重复触发 `kp.align`）；键 `study-agent:note-draft:v1:new|<id>`；800ms 防抖写入；离开/刷新前二次确认；打开时若有草稿弹“恢复/丢弃”，保存成功清草稿；用 `baseUpdatedAt` 与详情 `updated_at` 不等判陈旧，陈旧草稿直接丢弃。
- 决策 6（图片存储）：正文存稳定 token `![alt](note-file://<id>)`；加载时按 id Bearer 取 blob，`URL.createObjectURL` 替换预览，保存/写草稿时替换回 token；对象 URL 在卸载/重载/应用草稿时 `revokeObjectURL`；不用 base64 入正文，不存 MinIO endpoint/预签名 URL。
- 决策 7（上传与取图契约）：`POST /files?parse=false` 只接受 `image/*`，新记录直接 `parse_status=done/100/finished_at` 且不入队；`GET /files/{id}/image` 走 `get_file_status` 的本人/家长/教师权限，返回原字节 + `Content-Type`/`ETag=sha256`/`Cache-Control: private, max-age=300`/`nosniff`/inline；非图片 422，不泄露对象存储地址。
- 决策 8（图片上传交互）：图片按钮是下拉，真实用户选“上传图片”打开文件选择；上传成功回调 `onUploadImg` 的 blob URL 插入编辑器，同时 `image-uploaded` 通知表单登记 URL→token 映射，避免保存时把 `blob:` 写进库。
- 决策 9（校验）：标题必填 ≤200、正文必填 ≤200000、标签 ≤20 个且单个 ≤30；与后端 Pydantic 对齐；校验失败不发请求，错误就地展示。
- 决策 10（测试）：新增 Vitest 22 条（列表 5、编辑器 5、草稿 4、图片 5、查询 3），既有 17 条不回归，共 39；后端新增 6 条文件契约，全量 506；真实 Chrome/CDP 必须验证刷新后图片仍渲染，上传 201 本身不算通过。
- 决策 11（已知代价）：token 在导出到其它 Markdown 工具时是断链；图片 endpoint 一次读内存、无压缩/缩略图；草稿只在本浏览器且只按 `baseUpdatedAt` 判旧；无阅读页/文件夹/标签筛选/版本/回收站；删除笔记不删文件；编辑页 chunk 约 405 KB（gzip 140 KB）；教师/家长仍无工作区入口。
- 验证：`npm run test:run` **39/39**、`npm run build` 通过、pytest **506/506**；真实 1440×900 新建含公式与 64×64 PNG 的笔记，保存后 DB 为 `note-file://8`，刷新后 `.katex=1`、`img.naturalWidth=64`；草稿→离开取消/确认→重开恢复→保存清草稿；列表 12→翻页 2→20/页 12→关键词 1→学科 6→删除 11；console error 0、无横向滚动；验收数据与 MinIO 对象清理回 0。

## D-033 前端文件上传与解析状态（S2-13）

- 背景：S2-6 已有上传/解析状态、S2-8 已有解析 Worker，但前端 `/files` 仍是占位页；S2-13 要交付文件工作台。spec 见 `docs/spec/s2-13-files-ui.md`。
- 决策 1（历史列表）：新增 `GET /api/v1/files`，只返回本人文件，固定 `created_at DESC, id DESC`；出参 `PageData[FileSummaryOut]`，含 `chunk_count`，不做搜索/状态筛选。
- 决策 2（块数）：`chunk_count` 从 `parse_result_json.chunks` 派生，不给 `files` 加列、不加迁移；未完成/脏数据按 0。`GET /files/{id}/parse-status` 同步增加该字段。
- 决策 3（切片预览）：新增 `GET /files/{id}/chunks?limit=3`（1–20），按 `chunk_index` 升序，复用文件权限；前端只展示前 3 条，不做完整切片分页。
- 决策 4（类型）：文件页只收 `.pdf/.docx/.md/.txt`；图片继续走 S2-12 笔记编辑器独立入口，文件页不接图片/OCR。
- 决策 5（上传队列）：前端串行上传；每文件真实 Axios upload progress；上传后立即查一次状态，`pending/parsing` 每 3s 轮询，单文件最多 5min；终态刷新列表。不新增 SSE/WebSocket。
- 决策 6（失败重试）：前端保留本次会话的原始 `File`，失败卡片“重试”重新上传；不新增服务端重试/重解析接口，刷新后历史 failed 不能一键重试。
- 决策 7（列表轮询）：页面打开时若列表中有 `pending/parsing` 行，每 3s 批量查 `parse-status` 并原地更新；5min 后停止，避免无限请求。
- 决策 8（页面交互）：上传区支持拖拽/点选、多文件、拒绝类型提示、队列进度/状态/重试、清空已完成；列表列=文件名/类型大小/状态/切片数/上传时间/操作；失败行提示错误；完成行可开抽屉预览。
- 决策 9（分页）：与笔记页一致 `el-pagination`（10/20/50、总数、页码）；翻页请求 `page`/`page_size`；不做 URL query 同步。
- 决策 10（测试与验收）：后端新增 6 条契约、前端新增 17 条（常量 4、队列 5、上传组件 2、列表 6）；真实 Chrome 1440 + ARQ Worker 验收，不以 mock 代替上传链路。
- 决策 11（已知代价）：无文件下载/删除/签名 URL；失败重试仅当前会话；只预览 3 条；队列不跨刷新；轮询有 5min 上限；`chunk_count` 无独立列/索引；<1024 视口沿用全局 `body min-width:1024px` 横向滚动。
- 验证：pytest **512/512**；Vitest **56/56**；build 通过；真实 PDF 上传 → done/100/7 块 → 刷新持久化 → 抽屉 #1–#3；非法 PNG 前端拒绝；console error 0；1440 无横向溢出；验收账号/文件/笔记/切片/任务/MinIO 对象清理回 0。

## 待与导师拍板（方案附录 F 摘录）

| # | 决策项 | 备选 | 方案建议 | 状态 |
|---|---|---|---|---|
| 3 | 是否公网部署 | 公网 / 局域网 / 本地 | 先本地 + 局域网演示 | 已拍板 2026-10-15：仅本地（→D-009） |
| 4 | Agent 优先级 | 必做 / 选做 | 选做（M5） | 已拍板 2026-10-15：选做（→D-010） |
| 5 | 自测使用深度 | 偶尔用 / 持续自用 | 持续自用（每周记录） | 已拍板 2026-10-15：偶尔用（→D-011） |
| 7 | 学校对 AI 辅助编码的要求 | — | M0 就确认 | 已拍板 2026-10-15：允许（→D-012） |

> 已定项：#1 FastAPI（→D-001）、#2 数学（→D-002）、#6 软著不做（成果为答辩 PPT、演示视频与系统截图包）。
> 2026-10-15：附录 F 全部 7 项拍板完毕，决策悬空清零归档。


## D-034 前端知识点树管理（S2-14）

- 背景：S2-9 已有知识点树 CRUD 与 108 节点高中数学导入，S2-10 已有对齐与待确认 API，但 `/knowledge` 仍是 `ComingSoonView`；S2-14 要交付可用的树管理与待确认工作台。spec 见 `docs/spec/s2-14-kp-ui.md`。
- 决策 1（页面与角色）：`/knowledge` 单页两 tab「知识点树 / 待确认对齐」；教师/管理员可新增、改名、改描述/权重、拖拽、删除，学生只读；根节点「高中数学」前端锁定（不可拖、不可删，可改可加子节点）。教师/管理员无 redirect 登录默认 `/knowledge`，学生/家长仍 `/notes`；显式合法 `redirect` 优先，开放重定向拦截保留。
- 决策 2（树交互）：`el-tree` + 当前学科前端搜索（名称/编码）；`allow-drag` 禁止改根和搜索态拖拽；跨级移动与同级排序统一走一个原子接口，不做前端乐观排序，失败重载树。
- 决策 3（原子排序）：新增 `PUT /api/v1/kp/order`，入参 `parent_id`（可空=根）、`ordered_ids`（目标父级完整子节点集，1–200）、`moved_id`（可选，必须在列表内）；单事务完成“改父+重算后代 level+源兄弟归一+目标 order_no 重写”，204；校验重复/缺兄弟/跨学科/环/超 4 级。不能靠多次 PATCH 拼出可回滚的顺序。
- 决策 4（摘要）：`GET /kp/align/pending` 的 `PendingAlignOut` 增加 `note_excerpt`，从 `note.content_text` 去首尾空白后取前 300 字，超出补 `…`；字段默认空串，旧构造/旧客户端不破；不加列、不查完整正文。
- 决策 5（待确认）：一次一张卡，左侧笔记标题+摘要，右侧候选知识点+编码+置信度；`Enter` 确认、`Backspace` 忽略；busy 锁防重复，确认/忽略后本地推进，队列空自动重查；状态被并发改变（`confirmed/deleted` 非 1 或 `skipped>0`）告警并重载。只在该 tab 挂载键盘监听。
- 决策 6（实现）：前端新增 `types/kp.ts`、`api/kp.ts`、`views/kp/{treeUtils,Tree,PendingAlign,usePendingAlign,KnowledgeView}`、`components/kp/KpNodeDialog.vue`；后端只动 `schemas/kp.py`、`services/kp_service.py`、`api/v1/kp.py`、`schemas/kp_align.py` 及测试；不新增依赖/迁移/SCHEMA 变更。
- 决策 7（测试）：后端新增 12 条（排序 service 6 + API 4 + 摘要 2），全量 **524 passed, 1 warning**；前端新增 26 条（树工具 5、表单 3、树页 5、待确认 6、页面壳 3、redirect 3、登录 1），全量 **82 passed / 19 files**；`npm run build` 退出 0。真实浏览器另验，不以单测代替。
- 决策 8（真实联调抓修）：Element Plus 在 `dragend` 里先 `draggingNode.node.remove()` 再 emit `node-drop`，真实 Chromium 下 `dragging.parent` 已不可靠；首版按 `dragging.parent.childNodes` 取顺序，跨级移动时会退化到旧树/空列表。改为从 `dropNode`（移动后目标节点）的 `childNodes` 取完整兄弟顺序，并补树页测试。另修 `FilterNodeMethodFunction`/`AllowDragFunction`/`NodeDropType` 的 Element 类型对齐（`FilterValue`/`TreeNodeData`）。
- 决策 9（已知代价）：搜索仅当前学科前端过滤；无跨学科/全文/服务端搜索；无批量确认、撤销、操作历史、并发编辑冲突提示；根节点锁定只在前端；拖拽失败靠重载恢复；待确认一次一对请求，20 条可接受但不适合上千条；<1024 视口仍受全局 `body min-width:1024px` 影响（遗留 48）。
- 验证（真实浏览器 1440×900，CDP DOM + 网络/资源计数）：teacher `s214_teacher` 登录落 `/knowledge`，树 108 节点；新增子节点 `S214子节点增量测试` → 改名 `S214子节点已编辑` → 拖到「函数」下（DB `parent_id=117, level=3`）→ 删除；搜索「函数」只显示匹配路径；教师新建/删除 `S214最终检查` 复验。待确认造 20 条真实 `note_kps`（`confidence=0.660, source=ai, confirmed=false`），连续 Enter 20 次：卡片严格 20→0、无旧卡，`/kp/align/confirm` 资源计数 **20**，DB 20 行全部 `manual+confirmed`；另造 1 条按 Backspace：`/kp/align/reject` 计数 1、队列回空。student `s214_student` 登录落 `/notes`，访问 `/knowledge` 显示只读、无新增/编辑/删除、可拖拽节点 0；待确认空态正常。两角色关键流程 console error 0，两 tab `scrollWidth=innerWidth=1418` 无横向溢出。清理 21 条临时笔记+21 条 `note_kps`+2 个临时用户+全部 `S214%` 知识点，临时残留 0；学科 7 知识点仍 108，原有 3 条笔记/1 个用户保留。
- 已知不足（不粉饰）：本轮截图未做人工像素级目视走查，布局结论来自 DOM 尺寸/文本断言；教师/家长导航仍复用学生视图（历史问题）；没有真机触屏拖拽验证。


### 补充（2026-10-30）：教师/管理员笔记、文件入口
- 背景：S2-5/S2-6 规定笔记/文件为 student 私有资源，但侧栏对所有角色显示统一导航，教师点击会落 403 或空列表；用户要求先给“暂不支持查看”的占位，而不是无权限页。
- 决策：新增通用 `StudentOnlyView` 角色门；`/notes`、`/files` 路由去掉 `roles: ['student']`，改由 `NotesEntryView`/`FilesEntryView` 包裹。学生渲染原页面；教师/管理员/家长在内容区看到「暂不支持查看」+「前往知识库」，不再跳 403；直接访问笔记新建/编辑仍保持 student 限制。
- 验证：新增 3 条组件测试，前端全量 **85 passed / 20 files**；build 退出 0。真实浏览器 `teacher_demo` 登录 `/knowledge`，点侧栏「笔记」「文件」均显示占位、无 403，点「前往知识库」回到 `/knowledge`；console error 0。


## D-035 笔记索引服务与全量重建（S3-1）

- 背景：S1-2/S1-3 已有切片与向量化能力、S2-8 文档笔记已入库，但手写笔记从未进入 `note_chunks`，笔记正文无法被 RAG 召回；S3-1 要把“笔记正文 → 检索库”产品化并支持重建。spec/plan 见 `docs/spec/s3-1-index-service.md`、`docs/plan/s3-1-index-service.md`。
- 决策 1（Markdown 解析）：新增 `ai/parse/markdown.py`，把 `content_md` 拆为标题块 + 段落/代码块/表格，标题路径交给 S1-2 组织章节；`page_no=None`、`parser="text"`；图片只保留 alt，空小节标题丢弃。
- 决策 2（唯一入口）：`services/index_service.py` 是笔记索引唯一编排入口，内部只调 S1-3 `index_chunks(replace=True)`；保存与重建统一走 `index.note` 任务，不另写切片/向量化。`TASK_INDEX_NOTE` 常量放在 service（task 反向导入），避免 service↔task 循环导入。
- 决策 3（进度复用 async_tasks）：按笔记拆任务、payload 带 `run_id`，进度接口按 `run_id` 聚合状态与块数，不建新表/不加迁移。
- 决策 4（触发面）：创建笔记与“正文发生变化”的 PATCH 入队索引（best-effort，队列故障只 WARNING 不回滚保存）；只改标题/标签不重算向量；软删在同一事务删除 `note_chunks`。
- 决策 5（重建范围与代价）：全量重建覆盖全部未删除笔记（含文档笔记）；先清理软删笔记遗留切片再建任务；按 Markdown 重建会清空文档笔记的 `page_no/bbox_json`。
- 决策 6（并发）：不加分布式锁；同一笔记并发任务可能撞 `uq_note_chunks_note_chunk_index`，由 runner 3 次重试收敛；失败任务在进度接口 `failures` 中可见（≤20 条）。
- 决策 7（接口与权限）：`POST /api/v1/admin/index/rebuild`（202，返回 `run_id/total_notes/purged_chunks`）与 `GET /api/v1/admin/index/runs/{run_id}`（32 位小写 hex），仅 admin；空库 422、未知 run 404、队列不可用 500。
- 决策 8（测试）：新增 40 条（Markdown 12、service 11、task 4、admin 8、notes 4、并发用量回归 1），全量 **564 passed, 1 warning**。
- 决策 9（并发用量统计）：验收发现 S1-3 用共享 `EmbeddingClient.usage_tokens` 前后差值统计本次 tokens，S3-1 的并发任务会互相串账（note 79 单建 58，重建记成 662=588+74）。改为在 `index_chunks` 内累加本次 `on_batch` 的 `BatchStats.tokens`（批次回调只属于本次调用），补并发回归测试；块数、检索行为不变，`usage_tokens` 仍保留给脚本/其他调用方。
- 验证（真实 Postgres/Redis/Worker + 真实 DashScope Embedding）：创建验收笔记（note 79）→ `index.note` succeeded、2 块/58 tokens，`heading_path` 含 `函数`、`函数/单调性`；PATCH 追加唯一标记 → 新任务 succeeded、命中 1 行、总块数 2、重复分组 0；软删临时笔记 → 残留 0、孤儿 0；全量重建两次均 `percent=100 / succeeded=5 / failed=0 / chunks=39`，表内 39 行、重复分组 0（各笔记 2/6/8/21/2）；重建后 `page_no` 非空 = 0（确认代价）；student 重建与进度 403、匿名 401、坏 run_id 422、未知 run 404；`scripts/ask.py --user-id 25` 真实回答并引用笔记 #79 的「函数/单调性」片段。修复统计后再次重建 4 篇：tokens=70/588/437/1168、`chunks=37`、`failed=0`。
- 已知代价：全量重建丢文档页码/bbox；无单笔记索引状态列与单笔记重跑接口（只能整轮重建）；重建费用随笔记量增长；同一笔记并发保存可能短暂失败后重试；软删只清当前笔记切片，历史遗留靠重建清理。

## D-036 检索服务与 scope 过滤（S3-2）

- 背景：S1-4/S1-5 的 `retrieve_hybrid_reranked()` 只被脚本/评测直接调用，且对 `subject_id/kp_ids` 直接抛错，等于没有 scope；S3-2 要把检索封装成业务服务并暴露 student 接口。spec/plan 见 `docs/spec/s3-2-retrieval-service.md`、`docs/plan/s3-2-retrieval-service.md`。
- 决策 1（接口）：新增 `POST /api/v1/retrieval/search`，仅 student；同步 JSON；空知识库/无命中 200 + `hits=[]`。
- 决策 2（scope 字段）：`{subject_id?, folder?, start_date?, end_date?, chunk_types?}`；`notebook_id` 改为 `folder`，因为库里只有 `notes.folder` TEXT，没有 notebook 表。
- 决策 3（SQL 下推）：scope 条件全部在 `retriever.py` 内 join `notes` 下推；即使无 scope 也 join，并恒带 `notes.user_id` 与 `notes.deleted_at IS NULL`，软删残块不会被召回。
- 决策 4（日期语义）：按 `notes.created_at`；`end_date` 含当天（下界为次日 00:00 UTC）。
- 决策 5（开关）：`rerank` 请求可覆盖配置；`debug` 默认 false，开启才返回 vector/fulltext/fused 候选与分项耗时。
- 决策 6（服务边界）：SQL 只在 `ai/rag/retriever.py`；`services/retrieval_service.py` 只做校验、开关、标题一次批查与 DTO 组装；`answer_question` 不改，S3-5 直接复用本服务。
- 决策 7（性能口径）：HTTP 端到端、`rerank=false`、20 问、预热 3 次，含 DashScope 查询 Embedding，P95 < 500ms；同时记录 `embedding_ms/vector_ms/fulltext_ms` 分项。
- 决策 8（测试）：新增 retriever scope 4 条、service 10 条、API 9 条；删除 S1-4 旧的 subject/kp 拒参用例 1 条；全量 **586 passed, 1 warning**。
- 验证（真实 Postgres/Redis + 真实 Embedding/Rerank）：验收学生 1 篇笔记（subject=7、folder=函数）产出 2 块（note+question）。无 scope/subject7/folder=函数/当天日期各命中 2 块；subject8/folder=数列/创建前日期/题型 formula 各 0 块；`chunk_types=["question"]` 只返回 question 块。`rerank=true` 返回 `qwen3-rerank`、`fallback=false`、candidates=2、latency=193ms、scores=0.832/0.528。debug 返回 vector/fulltext/fused 各 2 条、`embedding_ms=148`。空库学生 200+0 命中；匿名 401/40100、teacher 403/40300。
- 验证（P95）：`scripts/retrieval_bench.py --runs 20 --warmup 3 --no-rerank`：wall P50=172ms / P95=229ms；server P50=163 / P95=223；embedding P50=154ms；PASS（<500ms）。
- 回归：`scripts/ask.py --user-id 28` 真实回答并引用笔记 #81 两个块（refused=否，llm_calls=1）；`scripts/retrieval_eval.py --user-id 28` 正常跑完 10 问（该账号仅 1 篇笔记，hit@5=2/10，rerank fallback=0/10）。
- 已知限制：带 `subject_id` 不命中文档笔记（S2-8 未回填 subject）；folder 是自由文本、无层级；P95 受外部 Embedding 支配（本机 154ms/次），无缓存；debug 响应最多 3×20 条完整块；kp/知识点过滤未支持；rerank 失败静默回退。

## D-037 Query 改写与意图识别（S3-3）

- 背景：S3-2 检索服务只接受单轮完整查询；多轮追问（“那它的前提条件呢？”）直接检索会丢失指代对象；chitchat 也会白跑检索。S3-3 在检索前做一次改写/意图识别。spec/plan 见 `docs/spec/s3-3-query-rewrite.md`、`docs/plan/s3-3-query-rewrite.md`。
- 决策 1（分层）：Prompt `ai/prompts/rewrite_v1.md` + 严格 JSON/重试/`RewriteOutput` 校验放 `ai/rag/query_rewriter.py`；`services/query_rewrite.py` 只做历史裁剪、缓存、降级、日志；service 不 import httpx/厂商 SDK。
- 决策 2（意图）：仅 4 类 `note_query/question_query/concept_explain/chitchat`；意图只做流程分支，禁止改变检索 scope、禁止生成多查询变体；chitchat 由同一次 LLM 调用生成 1–2 句 reply，不检索。
- 决策 3（历史契约）：调用方传入升序对话历史（不含当前问题）；S3-3 只取最近 3 个 user 轮及其后 assistant，单条空白折叠并截 300 字；不读会话表（S3-5 负责落库与鉴权）。
- 决策 4（缓存）：进程内 `OrderedDict` LRU + TTL（默认 3600s/256 条，线程锁）；key=`sha256(prompt_version|model|question|role:content...)`，只缓存成功结果；命中时 `cache_hit=True` 且 tokens/cost/latency 归零；`use_cache=False` 跳过读写；S3-7 换 Redis。
- 决策 5（降级）：LLM 超时/非 JSON/字段非法重试 2 次后，回退原问题 + `intent="note_query"` + `degraded=True` + 固定 reply，检索继续，禁止把异常抛给问答主链路；`RewriteError` 携带累计 `llm_calls/tokens/cost`，`LLMError` 因拿不到 usage 记 0。
- 决策 6（配置与边界）：6 个 `QUERY_REWRITE_*` 配置；无新接口/表/迁移/依赖；不改 `answer_question`、`retrieval_service`、API.md/SCHEMA.md/前端；LLM 调用加 `scene="query_rewrite"` 参数，`llm_call_logs` 落库仍归 S3-7。
- 决策 7（测试）：新增 24 条（AI 10、service 13、llm scene 1）；全量 **610 passed, 1 warning**；真实外部调用全部 fake。
- 验证（真实 DashScope LLM/Embedding + Postgres，`test1` id=18）：`scripts/rewrite_eval.py --user-id 18 --top-k 3` → hit@3 **9/10**、degraded 0/10、tokens 3958、cost ¥0.003802；10 条均 `concept_explain`、`is_followup=true`；`你好`→chitchat+reply；独立问题 `is_followup=false`。第 6 条“分段函数 f(f(-1))”改写正确，但检索 top3 未召回目标块 `note 77/chunk 11`（块存在），按约定不改样本/关键词。
- 已知限制：意图单次 LLM 判定、4 类粒度粗；缓存不跨进程/重启；历史截断可能丢条件；chitchat 误判会跳过检索；失败调用 token 无法完整记账；无 API/前端，S3-5 接入前只能脚本验收。

## D-038 Prompt 版本管理（S3-4）

- 背景：S1-6 的 QA Prompt 固定在 `ai/prompts/qa_v1.md`，改词要改代码/重启；任务卡要求存库、版本号、启用开关、缺变量报错与改动留痕。spec/plan 见 `docs/spec/s3-4-prompt-management.md`、`docs/plan/s3-4-prompt-management.md`。
- 决策 1（表与种子）：新表 `prompt_templates`；`UNIQUE(name, version)`；部分唯一索引 `uq_prompt_templates_active_name(name) WHERE is_active` 保证每 name 最多一条 active；迁移 `0006_s3_4` 内联种子 `qa/v1`（内容取自当前 `qa_v1.md`，末尾多一个换行、渲染无影响；`variables_json=["context","question"]`，`created_by=NULL`）。不改历史迁移。
- 决策 2（不可变版本）：不提供 PUT 改 content/删除；只 `POST` 新建 + `PUT /{id}/activate` 显式启用；`version` 省略自动 `vN+1`，显式重复 409；仅 admin，`created_by` 取当前用户，启用刷新 `updated_at`。
- 决策 3（读取链路）：生产只读库；`prompt_service.get_active_prompt()` 无 active 抛 `PromptTemplateError`，不静默回退文件；`answer_question` 增加可选 `prompt_template`，缺省仍读文件仅用于单测/兼容；`scripts/ask.py` 每次问答查一次 active 并传入，保证启用即时生效；无缓存（S3-7 再加）。
- 决策 4（渲染）：`prompt_builder.render_prompt_text()` 是唯一 Jinja2 文本入口（`StrictUndefined`、`autoescape=False`）；文件版 `render_prompt` 读文件后复用它；缺变量/空模板统一 `PromptTemplateError`，错误不携带上下文正文。
- 决策 5（上下文组装）：`build_context` 完全沿用 S1-6（4000 token 预算、rerank 排序、去重、截断、引用编号）；本卡只换 Prompt 来源，不改检索/回答/引用/拒答逻辑。
- 决策 6（范围）：本轮只迁 QA Prompt；`rewrite_v1.md`、`kp_align_v1.md` 仍读文件；无 SSE/会话/前端/新依赖；不改 `.env.example`。
- 决策 7（接口）：`GET /api/v1/admin/prompts?name=`、`POST`（201）、`PUT /{id}/activate`；`PromptCreate` 校验 name/version/content/variables；`PromptTemplateOut` 含全部字段；错误沿用 401/403/404/409/422。
- 决策 8（测试）：新增 26 条（模型 2、渲染/answerer 4、service 12、API 8）；基线 610 → **636 passed, 1 warning**；外部 LLM 全部 fake。
- 验证（真实 Postgres + 真实 LLM，`test1` id=18，2026-10-31）：
  - 迁移后 `qa/v1` active、`variables_json=["context","question"]`、`created_by=NULL`。
  - 基线 `scripts/ask.py --user-id 18 "错位相减法怎么用"` → `Prompt：qa/v1`，tokens 685/866/1551，cost ¥0.002280。
  - 通过真实 HTTP（TestClient + 临时 admin）`POST` 新建并启用 `qa/v2`（v1 末尾加“回答末尾必须写【PROMPT-V2】”）→ 同一问题回答末尾出现【PROMPT-V2】，`Prompt：qa/v2`，tokens 699/802/1501，cost ¥0.002163。
  - `GET` 历史返回 v2/v1；`PUT /1/activate` 切回 v1 → 同一问题标记消失，`Prompt：qa/v1`，tokens 685/862/1547，cost ¥0.002272；历史最终 v1 active、v2 inactive；临时 admin 清理，v2 保留为历史。
  - 激活首次实测触发 `uq_prompt_templates_active_name` 冲突：同一 flush 同时把旧版 false、目标 true，PG 在语句级检查部分唯一索引。修复为“先把同 name 全部置 false → `flush()` → 目标置 true → commit”，并加 FakeSession flush 断言；修复后真实 HTTP 激活成功。
- 已知限制：无删除/停用/回滚预览接口；`variables_json` 只做元数据与类型校验，不校验模板实际引用；每次问答多一次 DB 查询；多管理员并发激活无重试；行级留痕不能替代完整操作审计；rewrite/kp Prompt 未迁。

## D-039 问答流式与会话落库（S3-5）

- 背景：S3-4 以前只有脚本级同步问答；任务卡要求 `POST /qa/ask` SSE、会话/消息/引用落库、断连中断上游 LLM。spec/plan 见 `docs/spec/s3-5-qa-sse.md`、`docs/plan/s3-5-qa-sse.md`。
- 决策 1（LLM 层）：`LLMClient` 新增 `chat_stream`；默认实现调用一次 `chat` 后产出单块文本 + 最终响应，兼容只实现 `chat` 的 Client；OpenAI 兼容适配器用 `stream=true` + `stream_options.include_usage=true`，只解析 `data:` 行，`[DONE]` 结束；缺失 usage 时用 tiktoken 估算。
- 决策 2（时序）：`prepare_ask` 先落 user 消息（新会话同时落 conversations），再流式生成；assistant 与 citations 只在正常结束后用新 Session 落库；断连/流中错误不落 assistant。
- 决策 3（断连）：服务端关闭上游 `chat_stream`，保留 user 消息，不向已断开的客户端写 `error`；正常结束发 `done`，流中失败发 `error` 后关闭。
- 决策 4（引用）：S3-5 不做引用校验/重试/补丁；只持久化回答里合法的 `[n]` 子集，S3-6 `citation_checker` 接管；`meta.citations` 始终返回全部上下文引用。
- 决策 5（契约）：`conversation_id` 对外十进制字符串、库内 BIGINT；会话不存在/不属于当前学生统一 404/40400；chitchat/拒答也走 meta → 单 delta → done；无会话列表/删除/重命名，无限流。
- 决策 6（scope）：新会话按请求 scope 落 `conversations.scope_json`；已有会话请求未带 scope 时继承库内 scope，带 scope 时仅本次覆盖、不回写。
- 决策 7（测试）：新增 30 条（模型 3、LLM 5、answerer 3、service 13、API 6）；基线 636 → **666 passed, 1 warning**；外部 LLM 全部 mock。
- 验证（真实 Postgres + DashScope `qwen-plus`，`test1` id=18，2026-10-31）：
  - 首问 SSE：meta 1 / delta 181 / done 1，curl 总耗时 **24.480s**；`done.tokens=1949`、`latency_ms=24472`；DB user+assistant，4 条 citations（rank 1–4），`prompt_version=qa/v1`。
  - 追问（conversation_id=1）HTTP 总耗时 **3.688s**，同会话新增 user+assistant，引用接口返回 1 条。
  - chitchat `你好` **1.224s**，`prompt_version` 为空；不存在会话 → 404/40400。
  - 断连 `curl --max-time 3`：收到 meta + 20 delta 后超时（2776 bytes），DB 只有 user、无 assistant；日志出现 `qa_stream_disconnected`，上游未完成，连接已关闭。
- 断连实现细节：同步 `StreamingResponse` 在 uvicorn 取消时不会主动关闭同步生成器；路由改为 async 生成器，`run_in_threadpool(next, events, None)` 逐事件读取，`finally: events.close()` 保证断连时关闭上游。
- 已知限制：引用校验/重试归 S3-6；会话管理、前端归 S3-8；429 限流与 `llm_call_logs` 归 S3-7；未做并发压测。

## D-040 拒答与引用校验（S3-6）

- 背景：S3-5 只持久化合法 `[n]`，不做校验/重试/补丁；任务卡要求生成后校验引用、无引用知识陈述重试一次、仍失败加声明、拒答给建议。spec/plan 见 `docs/spec/s3-6-citation-check.md`、`docs/plan/s3-6-citation-check.md`。
- 决策 1（输出策略）：先完整生成并校验，再按块发 `delta`；不再逐 token 推送。用首字延迟换“重试/前缀不先发后改”。`meta` 仍在检索后立即发。
- 决策 2（检测粒度）：`services/citation_checker.py` 纯函数按段落/列表项/表格块检查；标题、代码块、纯公式块、补充声明、拒答文案跳过；块内任意合法 `[n]` 即视为已引用，越界编号单独记录。
- 决策 3（重试与兜底）：有问题且 `qa_citation_max_retries>=1` 时用“原 Prompt + 上版回答 + 纠正指令”重试一次；第二轮仍无任何合法引用→拒答；有合法引用→去越界编号，只给未引用块加 `【以下为模型补充，未在你的资料中找到依据】`，保留回答。
- 决策 4（拒答建议）：`done` 增加 `refusal_reason` 与 `suggestions:[{type:"rephrase"|"note",text,note_id}]`；正常回答 `[]`；建议不落库，重新加载后不保留。`refusal_reason` 取值 `no_context/low_score/empty_answer/no_valid_citation`。
- 决策 5（范围）：只改 SSE 链路；`answer_question`/`scripts/ask.py` 保持 S1-6 的“非法引用重试后拒答”行为。无新表/迁移/依赖/配置。
- 决策 6（断连）：`stream_events` 增加 `cancel_event`；静默生成阶段每收一个 chunk 检查，置位即关闭上游、不发 done、不落 assistant；路由 `finally` 置位并 best-effort close。
- 决策 7（测试）：新增 20 条（checker 12、answerer 1、service 5、API 2）；基线 666 → **686 passed, 1 warning**；外部 LLM/DB 全部 mock。
- 验收（真实 Postgres + DashScope `qwen-plus`，`test1` id=18，2026-11-01）：
  - `scripts/citation_eval.py --user-id 18`：5 条无依据问题全部拒答（3 条 `low_score`、2 条 `no_valid_citation`），5 条部分覆盖问题全部保留并带补充前缀，**10/10 通过**。
  - 真实 SSE 抽查（错位相减法步骤+历史）：`meta` 3.10s，首个 `delta` 15.06s，共 4 个 delta，`done` 15.10s；`tokens=2759`、`latency_ms=14672`、`suggestions=[]`；消息 32 落库 425 字、前缀 2 处、citations rank 1–3。
- 已知限制：块级检测是启发式，不判断引用是否真正支持该句；首字延迟显著增加；建议固定文案且不落库；断连只能在下一次 chunk 到达时关闭上游，不保证立即停止计费。

## D-041 缓存、LLM 调用日志与用量统计（S3-7）

- 背景：S3-7 要求 LLM/Embedding 调用可审计、重复问答可复用、管理端能按天看 token/成本。spec/plan 见 `docs/spec/s3-7-cache-llm-logs-usage.md`、`docs/plan/s3-7-cache-llm-logs-usage.md`。
- 决策 1（scene）：按真实调用扩展 `llm_call_logs.scene` 为 `qa/query_rewrite/kp_align/embed/mistake/gen/agent`；`status` 定稿 `success/failed`。`kp_align` 显式传 scene，不再借用 `qa`。
- 决策 2（问答缓存）：key 固定 `qa:v1:{user_id}:{sha256(scope)}:{sha256(规范化问题)}`，TTL 24h；**不把对话历史放进 key**，因此同一用户同一问题在相同 scope 下会跨会话命中。命中时不改写、不检索、不调 LLM/Embedding，但仍落新的 user/assistant 消息与 citations；`done.tokens=0`、`done.cached=true`。多轮指代问题可能返回首次答案，属于已接受的限制。
- 决策 3（Embedding 缓存）：key 为 `embed:{model}:{dim}:{sha256(text)}`，TTL 7d；包装器只把 miss 文本交给厂商，命中不产生厂商调用和调用日志；批量结果按原顺序回填，条数/维度不符抛 `EmbeddingError`。
- 决策 4（调用日志）：`llm_call_logs` 通过 `record_llm_call` best-effort 写入，独立 Session，任何失败只 WARNING，不影响主链路；适配器构造参数 `log_calls` 默认 false，只有 `get_llm_client()/get_embedding_client()` 打开，避免测试直连客户端时碰库。只记录计数/耗时/费用/状态，不记录 prompt 或回答正文；rerank 暂不落库。
- 决策 5（成本与用量）：费用按配置单价计算（`LLM_PRICE_INPUT/OUTPUT_PER_MILLION`、`EMBEDDING_PRICE_PER_MILLION`），不硬编码；`/admin/usage` 以 UTC 日历日聚合，返回 `totals` + 按 `date/scene/model` 的 items，失败调用 token/cost 按 0 聚合。
- 决策 6（配置）：新增 `CACHE_ENABLED`、`QA_CACHE_ENABLED`、`QA_CACHE_TTL_SECONDS`、`EMBEDDING_CACHE_ENABLED`、`EMBEDDING_CACHE_TTL_SECONDS`；Redis 不可用时缓存层 fail-open，问答仍可用。
- 决策 7（迁移）：新增 `0008_s3_7`，`cost NUMERIC(14,8)`、`user_id ON DELETE SET NULL`、scene/status CHECK 与三个索引；已对真实 Postgres 执行 `alembic upgrade head`。
- 决策 8（测试与验收）：新增模型 4、缓存 7、Embedding 缓存 4、调用日志/适配器 10、用量 5、QA 缓存流程 3，基线 686 → **719 passed, 1 warning**。真实验收（`test1` id=18，DashScope `qwen-plus`/`text-embedding-v4`，真实 Postgres+Redis）：最终一轮第一问 36.468s、`cached=false`、`tokens=4251`、新增 4 条调用日志、缓存已写入；第二问 **0.014s**、`cached=true`、`tokens=0`、**新增 0 条调用日志**、答案一致且落新消息。真实 `GET /api/v1/admin/usage?range=7d` 返回 200，累计 `totals.calls=8`、`prompt_tokens=5386`、`completion_tokens=3047`、`total_tokens=8433`、`cost_yuan=0.010392`、`avg_latency_ms=8730.88`，items 覆盖 embed/qa/query_rewrite；临时 admin 已删除。
- 已知限制：缓存 key 不含历史；缓存不区分 Prompt 版本/模型（版本变更后需手动清 `qa:v1:*`）；Redis 故障时每次请求最多多 0.5s 连接超时；失败调用无 usage 仍记 0；未做限流；未迁移 query_rewrite 的进程内 LRU 缓存。

## D-042 前端问答页与会话回放（S3-8）

- 背景：S3-5/6 已有 `POST /qa/ask` SSE 与引用，但前端没有可用的问答页、会话回放和引用跳转；S3-8 补齐 `views/qa/Chat.vue`、消息/引用组件、只读笔记页与 4 个会话接口。spec/plan 见 `docs/spec/s3-8-qa-chat.md`、`docs/plan/s3-8-qa-chat.md`。
- 决策 1（会话接口）：新增 `GET /qa/conversations`（最近会话有界列表，`limit` 1–100 默认 50）、`GET /qa/conversations/{id}/messages`、`PATCH /qa/conversations/{id}`、`DELETE /qa/conversations/{id}`（204，物理删除，依赖消息/引用级联）。`id` 对外字符串；标题 trim/折叠空白后 1–80 字，空标题回退首条 user 问题前 50 字，再回退「新对话」；越权/不存在统一 404。
- 决策 2（列表分页例外）：会话切换栏只需要“最近 50 条”，不套 `page_params/PageData`，已在 AGENTS §9.2 明确记录为 S3-8 例外；需要全量历史时另加分页接口，避免把分页器塞进侧栏。
- 决策 3（历史回放）：消息按 id 升序；引用左连接 `notes/note_chunks` 取标题/章节/页码，软删或缺失时 `note_available=false`；历史拒答只能按正文与 `REFUSAL_TEXT` 精确相等推导，`refusal_reason/suggestions` 当时未落库，回放只显示固定建议，不伪造原始原因。
- 决策 4（流式与打字机）：前端用 `fetch` + 自写 SSE reader（POST + Bearer 不能使用 EventSource），支持空行分帧、CRLF、多行 `data:`、注释行、跨 chunk UTF-8；协议仍是 `meta` → 0..N `delta` → `done/error`。打字机 16ms/帧、约 12–20 字/帧，`done` 先到也先排空队列再结束 `streaming`；切换会话/新建/删除时 abort 当前流。UI 消息用 reactive proxy，避免直接改原始数组对象不触发渲染。
- 决策 5（刷新与切换）：`/qa?conversation=<id>` 作为可刷新入口；加载会话时回放消息与引用，scope 取会话保存值；新对话提交首问后由后端自动建会话并回填 URL。会话列表切换/改名/删除均在前端完成，不新增路由页。
- 决策 6（引用跳转）：新增只读 `/notes/:id`（`note-read`），用 `MdPreview` 渲染；`snippet` 在 DOM 文本中做空白归一化匹配，支持跨文本节点，命中包 `<mark class="citation-hit">` 并滚动；匹配失败按 `heading` 最后一段滚到标题，并明确显示「未能精确定位引用片段」，不伪装成功；`note_available=false` 禁用点击。
- 决策 7（公式片段修正）：真实 UI 验收发现含 `$$...$$` 的引用片段在 DOM 中已被 KaTeX 渲染，原始 LaTeX 文本无法命中，原实现只能整段回退。`highlightSnippet` 改为多候选：完整片段 → 去公式片段 → 仅非公式行；同时补块级文本分隔，避免跨 `<h1>/<p>` 时丢空格。`NoteReadView` 不再在 `nextTick` 立即标注，而是监听 `MdPreview` 的 `on-html-changed` 后 80ms 去抖再标注，避免在预览未渲染完时改 DOM 导致段落丢失；`appliedQuery`/`applying` 防重复标注。
- 决策 8（scope 与权限）：沿用 `subject_id/folder/start_date/end_date`，不新增文件夹接口；`/qa` 仅 student，教师访问落到 `/403`；`/notes/:id` 的读写权限仍由后端 `GET /notes/{id}` 判定，前端只读页不额外放权。
- 决策 9（测试与验收）：后端新增 16 条（service 7 + API 9），全量 **735 passed, 1 warning**；前端新增 29 条/9 个文件（SSE 4、API 2、typewriter 3、highlight 6、CitationCard 2、ChatMessage 3、scope 4、Chat 3、NoteReadView 2），全量 **114 passed / 29 files**，`npm run build` 退出 0（仅 775KB chunk 警告）。
- 真实验收（2026-11-02，真实 Postgres + Redis + DashScope `qwen-plus`，`test1` id=18；Chrome headless + CDP 操作真实页面）：
  - 10 轮 SSE：总耗时 **93.7s**、done tokens 合计 **22,092**；首字延迟 1.590–34.627s；第 1 轮命中既有缓存（**248ms / cached=true / tokens=0**）、第 5 轮拒答（**2.868s / refused=true / 30 字**）、第 9 轮 chitchat 无引用（**1.599s / 0 citations**）；其余 7 轮均正常落库；10 轮共 30 条引用、20 条消息、1 条拒答。
  - 会话接口：列表 22 条、首条会话 20 条消息；改名 200「S3-8 验收会话」；临时会话删除 204，再查详情 404/40400。UI 侧新建→改名→删除临时会话（id=24）全链路通过，删除后自动回到 id=22。
  - 引用：真实点击引用落到 `/notes/55?snippet=...&chunk=255`，`mark.citation-hit` 命中「一、适用条件」+ 正文片段，无回退；含公式的 note 49 引用落到 `/notes/49?...&heading=单调性`，命中「单调性」+「定义：区间内自变量增大时函数值也增大。」，无回退、无正文丢失；章节卡片显示 `单调性`。
  - 刷新：`/qa?conversation=22` 刷新后 22 条消息、32 条引用、拒答样式 1 条仍在；教师账号访问 `/qa` 落到 `/403`「没有访问权限」。
  - UI 流式采样：19 次/250ms，首帧 7 字符、最终 827 字符；短缓存答案只观察到 3 个长度（打字机约 0.2s 排空），未做逐帧像素级流畅度测量，顺滑度以 typewriter/SSE 单测与首 delta 时间为准，不夸大为逐帧数据。
- 已知限制：会话列表固定最多 50 条且无分页；历史拒答原因/建议不落库；引用高亮依赖文本匹配，公式/强排版片段按“去公式正文”命中，仍可能退化为章节定位；`message_citations` 不存标题/章节，依赖切片重建；删除会话物理级联、不可恢复；未引入浏览器自动化依赖，本轮用本机 Chrome CDP 做验收，CI 无 E2E。

## D-043 在线评测与检索三配置（S3-9）

- 背景：S1-7 评测是脚本级、旧 gold 25–106 已与当前 37 块语料（250–286）脱节；S3-9 需要在线 API 链路、三配置对照、40 条 M2 数据和逐题核对。spec/plan 见 `docs/spec/s3-9-online-eval.md`、`docs/plan/s3-9-online-eval.md`。
- 决策 1（检索模式）：扩展现有 `POST /api/v1/retrieval/search`，加可选 `retrieval=vector|hybrid|hybrid_rerank`；缺省保持 `rerank`/配置的旧行为。`vector`/`hybrid` 与 `rerank=true`、`hybrid_rerank` 与 `rerank=false` 在 schema 层 422。service 里 `vector` 复用 `retrieve_hybrid` 的向量召回后截前 `top_k`，不是独立纯向量 SQL；延迟口径因此偏保守，文档明确标注。
- 决策 2（问答费用）：`done` 增加 `cost_yuan`，等于所有回答尝试（含重试）+ 查询改写的真实 LLM 费用；缓存命中/未调 LLM 为 `0.0`。不新增费用表，不改既有 done 字段。
- 决策 3（数据重建）：新建 `eval/datasets/qa_set_m2.jsonl`，保留 S1 `qa_set.jsonl` 与原结果；M2 固定 40 条（30 应答 + 10 应拒），30 条 gold 全部在 250–286，已用数据库核对存在；`load_dataset` 的 `min_items/max_items` 显式传 40。
- 决策 4（在线边界）：`eval/run.py --api-base-url` 只走 `httpx` + `/api/v1/*`，不 import 业务 service、不直连 DB；鉴权 `--token` > `EVAL_TOKEN` > `--username/--password`/`EVAL_USERNAME/EVAL_PASSWORD`，token/密码不写文件、不写结果、不写日志。回答每题新建会话，结束 best-effort DELETE，失败只告警。在线结果保留回答正文与引用快照供逐题核对，仅落本地 `eval/results/`，不存 token/密码。
- 决策 5（三配置）：`--config all` 仅在线模式；输出固定 `s3-9-{config}.json/md` 与 `s3-9-compare.md`，拒绝 `--output/--md-output`。vector/hybrid 只检索；只有 `hybrid_rerank` 跑 40 条真实回答。
- 决策 6（引用口径）：在线客户端只把正文实际出现的 `[n]` 解析为引用，不用 `meta.citations` 全量上下文；否则引用精确率会被上下文条数稀释。gold 仍是人工锚点，多引相关块不判错，但精确率按 gold 计。
- 决策 7（拒答口径）：自动指标严格按 `done.refused`；`chitchat` 分支的“礼貌拒绝”（天气/股票/菜谱等）不置 `refused`，因此自动拒答准确率 82.5%，人工按“是否给实质答案”判 10/10。该差异作为产品语义问题记录，不通过改评测脚本抹平；后续若要统一，应改查询改写/问答状态机。
- 决策 8（测试与验收）：新增 schema 8、service 分支 4、API 7、数据集 4、在线客户端 7、编排 3；全量 **770 passed, 1 warning**。真实三配置（2026-11-02 02:34–02:43，`test1` id=18）：vector hit@5/MRR/检索 14ms 为 **1.000/0.957/14ms**，hybrid **1.000/0.790/15ms**，hybrid_rerank **1.000/0.978/14ms**；生产回答引用精确率 **0.897**、命中率 **1.000**、拒答准确率 **82.5%**、平均 tokens **1929.7**、平均回答延迟 **12901ms**、总费用 **¥0.088384**。
- 实测偏差：首次重跑命中 S3-7 QA 缓存（tokens=0/费用=0），清空 `qa:v1:*` 后重跑；在线客户端初版把全上下文当引用，精确率 0.228，改为正文引用后 0.897；q028 正文“未使用 [2]–[6]”被正则误计为引用。
- 已知限制：40 条/37 块统计意义有限；gold 是 AI 预标注 + 用户抽查；q014 题面有歧义；chitchat 拒绝与 RAG 拒答语义未统一；vector 非严格纯向量基准；在线评测依赖本机服务/Key/网络；未自动打 `m2-rag-done` tag，未 push。

## D-044 题库与试卷切题（S4-1）

- 背景：S4-1 要求建题库两表、上传 PDF/DOCX 试卷异步切题、判重、自动挂知识点，并提供人工审题的编辑/合并/拆分兜底。spec/plan 见 `docs/spec/s4-1-question-bank.md`、`docs/plan/s4-1-question-bank.md`。
- 决策 1（题库公共化）：`questions` 不带 `user_id`，作为公共语料对所有登录用户可读；写限创建者本人或 teacher/admin（`ensure_can_edit`）。学生新增/导入的题目 `origin` 只能 `upload`，否则 403/40300。理由：题目本身不含学生隐私，重复存储无意义；S2-3 的数据隔离清单只覆盖学生私有数据。
- 决策 2（数据模型与判重契约）：新增 `questions`（含 `stem_hash TEXT NOT NULL` + `UNIQUE(subject_id, stem_hash)`、`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`embedding VECTOR(1024)` + HNSW）与 `question_kps`（复合 PK + `idx(kp_id)`，`weight NUMERIC(8,6)` 存对齐分）；枚举 `QuestionOrigin` / `QuestionType` 一律 TEXT + CHECK。判重两道闸：`normalize_stem`（去题号→NFKC→去空白→去首尾标点）后哈希命中唯一键，未命中再比向量余弦 ≥ 0.92。**拆分/合并必须给 `check_duplicate` 传 `exclude_ids` 排除源题自身**：源题在提交前仍在库，拆出的子串/合并后的拼接与原题余弦必然 ≥0.92，不排除会把“自己”判成 409。
- 决策 3（切题与部分成功）：`ai/extract/splitter.py` 规则预切（大题标题 + 行首题号 + 声明题数；页码/答题卡行全局剔除；首大题标题/首题号之前内容丢弃），块数不符或题号不足时 `degraded=True`，改用 `mode=block` 逐块抽取（不重新喂整卷）；一个 block 都切不出（含完全没有题号）则任务直接失败。`ai/extract/question_extractor.py` 单题/整块统一 schema，严格 JSON + Pydantic + 最多 2 次重试。单题最终失败只进任务 `result.failed_items`（`index` 为卷面题号，`reason` 截 200 字），任务仍 `succeeded`；整卷无文本/扫描件/全部抽取失败才 `failed`。任务 handler 只 `flush` 不 `commit`，由 runner 统一提交，避免半卷脏数据。任务 payload 只带 `file_id` + 冗余 `subject_id/origin/created_by`，不把题面正文写进 `async_tasks`。
- 决策 4（知识点对齐，spec D-10 重写）：向量召回同 subject 全部知识点 top-10 → **由 LLM 在候选内选择**（复用 `ai/align/extractor.py::extract_matches` 与 `ai/prompts/kp_align_v1.md` 的候选内选择 prompt，题目借用“试题”标题）；只接受候选内 `kp_id` 且 `confidence ≥ 0.5`，每题最多 3 条，`weight = 0.6*cos + 0.3*keyword + 0.1*prior`（6 位小数，`combine`）。**0.75 不再是“是否挂”的门禁**，只保留为 LLM 失败时的确定性兜底阈值；LLM 失败记 WARNING `question_align_llm_failed` 并走兜底，建题不失败。理由：题目↔知识点名的余弦上限实测 ~0.55，`0.6*cos` ≤0.33，原方案“不额外调 LLM、按 0.75 挂”真机 20 题只挂上 1 条（最高分 0.688，0.75 不可达）。代价：每卷多约 20 次 LLM 调用、耗时增加约 20–40s（修复后首导 132.5s / 二导 80.3s 已含此开销）。
- 决策 5（接口契约与偏差）：新增 8 个路由（导入/列表/详情/新增/编辑/拆分/合并/删除），任务查询复用 S2-7 的 `GET /tasks/{task_id}`。列表入参实现为 `mine: bool`（前端传 `mine=true`），不再用 spec 的 `created_by=me`；详情出参只有 `kps[{kp_id,kp_name,kp_code,weight}]`，没有 `kp_ids`；队列不可用沿用 S2-7 的 `500/50000`（不改异常体系，spec 原写 `503/50300`）；split/merge 的参数错误（切点不存在、跨学科等）统一走 `InvalidParamError` → `422/42200`，不单独造 400。
- 决策 6（文件通道）：`file_service` 的 `parse=false` 现在是“只存原件、不解析”：图片自 S2-6 起即可（编辑器插图），PDF/DOCX 自 S4-1 起放行（试卷原件切题用），二者都写 `parse_status=done`、不入 `parse.document`、不建笔记/切片；MD/TXT 等文本类仍必须 `parse=true`（否则前端拿不到解析结果）。
- 决策 7（前端）：新增 `/questions`（审题页）与 `/questions/import`（导入页）；导航固定为 01 笔记 / 02 文件 / 03 知识库 / **04 题库** / 05 智能问答 / 06 错题本 / 07 复习计划（`MainLayout.spec.ts` 断言由 6 改 7）。导入页轮询 1.5s，成功后跳审题页并带 `?source_file_id=`；审题页支持编辑、新增、多选合并（2–10）、按标记拆分、删除与 KaTeX 预览；学生对他人的题只读。保存时只在**知识点集合真的变化**时才下发 `kp_ids`——后端收到就会整体重建链接并写 `MANUAL_WEIGHT=1.0`，无条件下发会把自动对齐的真实权重刷平，S5-1 组卷依赖该权重。
- 决策 8（测试与验收）：新增迁移 `0009_s4_1`（down_revision `0008_s3_7`）；终审修复后后端 **865 passed, 1 warning**，前端 **125 passed / 30 files**。真机验收（真实 Qwen + 真实 Postgres/Redis/MinIO + 本人自编 20 题卷，2026-11-03，修复后干净全量跑，任务 id 98）：`succeeded`，`detected_count=20 / expected_count=20 / created=20 / duplicated=0 / failed_items=[] / degraded=false / warnings=[]`，`elapsed_ms=131948`（**132.5s**）；二次导入 `created=0 / duplicated=20`、**80.3s**；知识点 **20/20 题挂上、32 条链接**（1 条×12 题、2 条×4 题、3 条×4 题）；题型 单选 8/填空 4/解答 8；`difficulty` 1 分×4、2 分×12、3 分×4；`verified` 全 true；拆分 **200** 返回 2 题、原题 `404`、题数 +1；合并 **200** 返回新题 id 45、原 2 题 `404`、挂 3 条知识点；删除 **204** 且 `question_kps` 残留 0；删 1 题后重导 `created=1 / duplicated=19`；PATCH 持久化；难度非法值 422/42200；PNG 导入 400/40000；合并 1 道题、含不存在/跨学科 id → 422。
- 实施中的修正（真机发现）：`check_duplicate` 原实现未排除源题自身，拆分/合并时源题仍在库，拆出的子串/拼接后的题干与原题余弦 ≥0.92，真实题拆分直接 409；已为 `check_duplicate` 增加 `exclude_ids` 参数（split 传 `[question_id]`、merge 传全部 `unique_ids`），判重语义不变，并补 3 条测试。修复后重跑得上述验收数字。
- 实施中的修正（终审代码评审 I1–I7，Critical 0 条、Important 7 条全部修复或转为已知限制）：
  - `parse=false` 放行范围按决策 6 修正为“图片（S2-6）/ PDF·DOCX（S4-1）”；MD/TXT 等文本类仍必须 `parse=true`，此前“图片仍必须 parse=true”的表述有误。
  - PATCH：`qtype/difficulty/origin/verified` 传 `null` → 422；题干只改空格/标点也真落库；`UPDATE` 撞 `UNIQUE(subject_id, stem_hash)`（含并发）与 INSERT 一样翻成 409/40900；手工新增/编辑与抽取共用 `validate_question_shape`，按“更新后的有效状态”做题型↔选项交叉校验。
  - 读路径与兜底：`kps[].weight` 出参改为 JSON number（DB 仍 NUMERIC）；列表排序追加 `id DESC` 兜底；整卷兜底 `max_tokens` 按题数伸缩为 `min(8192, max(2048, 400*expected_count))`；Prompt 的学科名取 `subjects.name`、`expected_count=None` 不渲染。
  - 审题页保存只在知识点集合真变化时下发 `kp_ids`，避免把对齐权重重置为 1.0（0.75→LLM 候选内选择已在决策 4，不重复记录）。
- 已知限制：`difficulty` 由 LLM 主观判断（实测集中 1–3）；`stem_latex` 本次未落库（保留 NULL）；知识点对齐是近似的，复合题通常 1–2 条；扫描版 PDF 不支持（S4-2 拍照识别）；判重不拦“同题换数字”的变式题；题库公共且无审核流；拆分/合并/删除硬删不可撤销；试卷原件与普通附件在文件页混排。

## D-045 错题录入、状态机与拍照识别（S4-2）

- 背景：S4-2 要求建 `mistakes` / `mistake_analyses` 两表，提供「题库选」与「拍照上传」两种录入、复习驱动的状态机、按状态/错因/知识点/时间筛选的列表与三组统计，并补前端列表/录入/详情三页。spec/plan 见 `docs/spec/s4-2-mistakes.md`、`docs/plan/s4-2-mistakes.md`。
- 决策 1（数据模型与私有性）：新增迁移 `0010_s4_2`（down_revision `0009_s4_1`）；`mistakes` 带 `uq_mistakes_user_question`、`ck_mistakes_status`、`ck_mistakes_correct_streak`、三个索引与三个 FK（`user_id` NO ACTION、`question_id` RESTRICT、`image_file_id` SET NULL）；`mistake_analyses` 带 `UNIQUE(mistake_id)`、`ck_mistake_analyses_cause_type`、`kp_ids` **GIN**、`mistake_id` CASCADE。枚举 `MistakeStatus` / `CauseType` 一律 TEXT + CHECK，值集与迁移一致。错题是学生私有数据：所有查询显式带 `user_id`，他人记录与不存在统一 404/40400，不泄露存在性。
- 决策 2（幂等复用，不复 409）：同一 `(user_id, question_id)` 再录一次不报 409，而是复用既有行并重置 `status=待订正`、`correct_streak=0`；`last_review_at` **不动**（deviation d-1，以代码为准；spec 原写 `last_review_at=now` 已勘误）。响应仍为 **201** 且 `created=false`，前端「再记一次」可以无脑点。并发重复录入由唯一约束兜底：捕获 `IntegrityError`（此时 `_commit` 已回滚）→ 重查赢家 → 按同一语义重置 → 再提交；查不到赢家才抛 `ConflictError`（409/40900），不把 `IntegrityError` 冒成 500。
- 决策 3（状态机只由 review 驱动）：`POST /{id}/review` 是唯一能改 `correct_streak` 的入口。`correct=true` → streak+1，`>= MASTERY_STREAK(2)` → 已掌握，否则已订正；`correct=false` → streak=0 且回待订正；三种情况都刷新 `last_review_at`。已掌握后再答对，streak 继续递增（spec 未要求封顶，不人为造上限）；再答错同样回退。`PATCH /{id}` 的 `status` 只是改标签，**不改 streak、也不刷新 `last_review_at`**——「连续答对」是行为事实，不能靠改标签伪造（D-7）。
- 决策 4（列表与统计口径）：列表 9 个查询参数（`status` / `cause_type` / `kp_id` / `created_from` / `created_to` / `page` / `page_size` / `sort_by` / `order`）；`cause_type` 与 `kp_id` **全部用 EXISTS**（不 JOIN），避免一题多知识点/多诊断时产生重复行、破坏分页与 count；`kp_id` 命中「题目挂载的 KP」**或**「诊断 `kp_ids @>`」任一；排序白名单 `created_at`（默认）/ `last_review_at` / `status` / `correct_streak`，一律追加 `id DESC` 兜底；一页的 `kp_names` 与诊断 `cause_type` 各用一次 `IN` 批查（空页不发查询），不做 2N 次逐行查询。统计三条 SQL 聚合：`total` = `by_status` 三项之和；`by_status` 按 `MISTAKE_STATUSES` 固定顺序补 0；`by_cause` 连接诊断表，按 `count DESC, cause_type` 稳定排序；`top_kps` 取前 10，按 `count DESC, kp_id`（一题多 KP 在各 KP 各计 1 次）；三条都带 `user_id` 与日期边界。
- 决策 5（拍照链路与事务边界）：`POST /mistakes/photo` 的 `subject_id` 在 **query**，`file` 与 `my_answer_md` 在 **multipart**；返回 202 任务 `mistake.recognize`，客户端用 `GET /tasks/{task_id}` 轮询。入口先 `ensure_subject_exists`，再用 `file_service.detect_type` 按扩展名预校验 mime，**然后**才上传，避免类型不符时留下孤儿 `files` 行；上传后再用 `record.mime` 兜底扩展名与 magic 不一致。任务 handler **不 commit**（runner 统一提交）；`task_create_mistake` 是唯一 `flush()` 取 id 的地方——runner 关 `autoflush`，不 flush 时 `mistake.id` 恒为 None，且 flush 顺带把唯一冲突收进 handler 的 try，而不是留到 runner 的成功提交里炸。识别失败只让任务 failed，图片仍留在 `files`（原图是学生唯一证据）。
- 决策 6（作答优先级与低置信）：`my_answer_md` 取「学生手填 > 视觉识别 > None」，`used_answer_source ∈ {student, vision, none}`；识别不出作答就留 null，**不猜**——错因诊断（S4-3）会把 `my_answer_md` 当证据，编造的作答会污染结论。`confidence < 0.5` 标记 `low_confidence=true`（**等于 0.5 不算低**），题目仍入库，只提示人工复核；confidence 是模型自评、未校准，不参与硬判定。
- 决策 7（d-11：拍照上传只收 PNG/JPEG）：`file_service.TYPE_TABLE` 与 `upload_allowed_extensions` 都没有 webp，补 WebP 属跨模块改动，本卡不做；`ai/vision/mistake_ocr.ALLOWED_MIMES` 仍含 webp 作防御，但本链路不可达。由此 `/photo` 缺文件或非 PNG/JPEG 返回 **422/42200**，与 `/questions/import` 的 `400/40000` 不一致；这是现状，已在 API.md 节内注明，不在本卡统一异常口径（改它会动 S4-1 的导入契约）。
- 决策 8（契约偏差回填）：按既有编号把错题接口写进 `API.md` **§6**（spec/plan 原写 §5.6）；列表排序参数实际是 `order`（spec §8 原写 `sort_order`）；`GET /{id}` 的详情是扁平字段（`stem_md` / `my_answer_md` / `analysis` 等），不是嵌套 `question` 快照；删除 204 无体、`PATCH status=null` → 422、重复录入 201 + `created=false` 均以本文与 API.md 为准。
- 决策 9（测试）：后端新增 6 个测试文件（模型、服务、任务、视觉、视觉消息、接口），基线 865 → **952 passed, 1 warning**（本卡实测）；前端基线 125 → **180 passed**（`npm run test:run`，控制器实测）。真机验收（真实 Qwen-VL + 真实 Postgres/Redis/MinIO、10 道题库录入 + 3 张合成图 + 状态机/筛选/引用保护 + 浏览器）由控制器另行执行；本文件不写尚未跑出的验收数字。
- 已知限制：错因诊断、变式题与 `similar_questions_json` 归 S4-3，本卡 `analysis` 恒 null；拍照只收 PNG/JPEG，WebP 未开放；`last_review_at DESC` 时 NULL 行按 PostgreSQL 默认（DESC 下 NULLS FIRST）排序，口径未定（见 PROGRESS 遗留 88）；视觉识别只验证过印刷体合成图，手写体效果未验证；一图一题、无图片预处理；拍照建题会进入公共题库，低质量照片题可能污染题库（遗留 82）；错题硬删不可恢复；无教师/家长查看学生错题的接口。
## D-046 错因诊断服务（S4-3）

- 背景：S4-3 要求错题录入后自动给出「为什么错」，落 `mistake_analyses`，并在详情页展示与手动重跑。spec/plan 见 `docs/spec/s4-3-mistake-analysis.md`、`docs/plan/s4-3-mistake-analysis.md`。
- 决策 1（解耦与触发）：诊断与录入解耦——`create_from_question` 成功后 best-effort 入队 `mistake.analyze`，入队异常只 WARNING 不回滚录入（同 S3-1 创建笔记后 best-effort 入队索引）；自动触发默认 `skip_if_analyzed=True`（已有诊断跳过，避免反复烧钱），手动接口 `POST /mistakes/{id}/analyze` 默认 `force=true` 覆盖。
- 决策 2（1:1 覆盖式 UPDATE）：`uq_mistake_analyses_mistake_id` 决定一题一份诊断；重跑走 UPDATE 原地改字段并刷新 `created_at`（语义定为「最近一次诊断落库时间」），不新增列、不保留历史。upsert 后显式 `session.flush()`：`autoflush=False` 下不 flush，约束错误会逃出 handler 的 try，任务会卡在 `running`（S4-2 C1 教训）。
- 决策 3（`unknown` 由代码强制）：`my_answer_md` 为空时，无论模型输出什么，一律覆盖为 `cause_type="unknown"`、`secondary_causes=[]`、`error_step=None`，只保留题目讲解；并记 `mistake_analyze_unknown_answer` 日志。模型可能编错因，代码兜底才能保证口径，前端也能据此隐藏错因区。
- 决策 4（证据校验）：`error_step` 必须包含学生作答里 ≥2 字的片段，否则丢弃为 `None`；宁可空着，也不要泛泛的「计算错误」。
- 决策 5（上下文与降级）：上下文固定六块（题干截断 2000 字、选项、标准答案、学生作答截断 1500 字、题目已挂 KP ≤3、KP 父节点名 ≤5、笔记 top-3 片段每条截断 200 字）；`kp_ids` 直接取 `question_kps`（不重新对齐，避免与题库展示不一致）；笔记检索失败只 WARNING 降级为空，诊断照常跑。
- 决策 6（Prompt 与口径，v2）：Prompt 走文件 `ai/prompts/mistake_analyze_v2.md`（S3-4 约定只有 QA 读 `prompt_templates` 表），`scene="mistake"`（白名单值，S4-2 C1 踩过 `mistake_ocr` 不在白名单）。v2 起把「错因判定口径」写进 Prompt：截断→时间不足 > 读题/所求→审题偏差 > 概念/公式（内容记错=知识遗忘，理解用错=概念不清）> 路径方法→方法不当 > 纯运算→计算失误。原因是 v1 只给 6 个枚举时，自测集主因命中率只有 36.7%，六类边界各说各话、指标不可复现（详见证据文档）。
- 决策 7（任务与事务）：`tasks/analyze_mistake.py` 沿用 S2-7 约定，handler 不 commit，`payload` 只带 `mistake_id`/`user_id`；`force=false` 且已有诊断时返回 `{"mistake_id": N, "skipped": true}` 且任务 `succeeded`。`TASK_ANALYZE_MISTAKE` 常量定义在 service（task 反向导入），`TaskQueue` 走 `TYPE_CHECKING` + 函数内延迟导入 `task_service`，避免 `app.tasks.__init__` 循环导入。
- 决策 8（验收口径与自测集）：准确率口径 = 主因命中率（目标 ≥70%），另记主因或次因与混淆矩阵；数据是**构造的自测集**（S4-1 题库 + 30 条人工作答，6 类各 5 条），报告一律标注「自测集，非真实学生数据」。三轮数字（36.7% / 63.3% / 86.7%）与"看着错误调 Prompt 的过拟合风险"全部写进 `.sdd/s4-3/acceptance-evidence.md`，不挑数字。
- 决策 9（测试与契约）：后端基线 952 → **999 passed, 1 warning**；前端 180/35 → **187 passed / 35 files**。`API.md` §6 补 `analysis` 新字段与 `POST /mistakes/{id}/analyze`（202、`force` 默认 true、404/422/500）；`SCHEMA.md` §5.4 补两列两 CHECK 与 `prompt_version` v2。
- 已知限制：`similar_questions_json` 仍未写入（S4-4）；`confidence` 实测集中在 0.9–0.95，未校准；"时间不足"在"有半截结论"时判定不稳定（#26）；浏览器级 E2E 未做（无 Playwright，§2.1 不擅自加依赖）。

## D-047 变式题生成与自检（S4-4）

- 背景：S4-3 把 `similar_questions_json` 留空，S4-4 要按方案 6.5 生成变式题并过「格式校验 + 独立复算」。spec/plan 见 `docs/spec/s4-4-variant-generation.md`、`docs/plan/s4-4-variant-generation.md`。
- 决策 1（触发与数量）：**只手动触发**（`POST /mistakes/{id}/variants`），一次固定 3 道，不做自动生成——一道错题自动跑一次生成会烧掉 4~12 次 LLM 调用，学生录 10 道错题就是几十次调用，成本不可控。前置条件两道 409/40900：无诊断（「请先完成错因诊断」）、题干 <10 字（「这道题题干太短」）。
- 决策 2（三分工，不设第三个 LLM 判官）：生成只产出结构化题目（`variant_generator`）；复算**只给题干与选项、不给答案**让模型重解（`variant_verifier`，独立侧的关键）；判定是纯函数 `compare.match_answers`（选项集合 → 数值容差 1e-6 → 同义组 → 多解集合 → 字符串）。**不加「让模型判断两份答案是否一致」的第三方角色**：那等于让同一族模型互相打分，成本翻倍且无独立证据。最多 2 轮 / 12 次调用。
- 决策 3（存储与入库）：结果写 `mistake_analyses.similar_questions_json`（版本化 v1，覆盖式，不建新表、不加迁移，`alembic heads` 仍 `0011_s4_3`）；**不自动入库**，用户在详情页逐题「存入题库」才建题（`POST .../variants/{variant_id}/accept`），入库时 `origin=ai`、`verified=false`、`tags=["AI变式"]`、知识点链接继承原题。accept 幂等两道：JSON 里的 `accepted_question_id` + 题库 `stem_hash` 判重；建题 commit 与回写 JSON 的 commit 非原子，靠重试收敛（spec §6.4）。
- 决策 4（失败语义）：**生成彻底失败（重试耗尽）时抛错 → 任务 `failed` 且旧 JSON 保持不动**；已有通过项时保留部分结果并照常 `succeeded`。真机踩过：原实现无论成败都覆盖 JSON，一道题生成失败把上一次的结果也清了（spec §5.5）。
- 决策 5（确定性质量护栏，验收后补）：`ai/gen/quality.py` 两条零成本护栏在复算前跑——① 同批题干指纹重复（NFKC + 去空白）直接丢重；② 解析命中「？错」「重算」「改为」等 14 个自问自答标记直接判废。理由：真机抓到同批两道同题，以及解析一边算一边改题导致题干与答案不符（§5.2.1 有原文）。
- 决策 6（真机调参四次，全部留存证据在 `.sdd/s4-4/progress.md`）：生成 `max_tokens` 2000→**3500**（解答题常需 1700~2500，2000 处被截断成非法 JSON）；复算 1200→1800→**2600**；生成 `analysis_md` 上限 1500→**2000**；复算 `reasoning_md` 超 1500 字符改为**截断不判失败**（展示字段，判死会白跑整题）。另加 `ai/gen/json_repair.py::loads_lenient_json` 三档兜底修 LaTeX 反斜杠（`\sqrt` 非法转义、`\frac` 变被吃成换页符）。
- 决策 7（测试与契约）：后端基线 999 → **1082 passed, 1 warning**；前端 187/35 → **194 passed / 35 files**。`API.md` §6 补两个接口 + 变式题说明、§7 说明通用「凭空出题」仍未实现；`SCHEMA.md` §5.4 补 `similar_questions_json` v1 结构。
- 已知限制：复算与生成若**犯了同一个错**，比对仍会通过（m=44 变式2 题面自相矛盾、两侧都算成 -1）；解析长度、模板腔调仍由模型决定；不生成图形题/需要画图的题；一次固定 3 道不可指定；已入库的变式题与普通 AI 题一样没有审核流；浏览器级 E2E 未做（无 Playwright，§2.1 不擅自加依赖）。

## D-048 知识图谱关系构建与人工校验（S4-5）

- 背景：`knowledge_edges` 只有表结构没有数据；S4-6 的图谱可视化与「按前置推荐」都要求先有关系。spec/plan 见 `docs/spec/s4-5-knowledge-graph.md`、`docs/plan/s4-5-knowledge-graph.md`。
- 决策 1（新增三列 + 状态机）：`knowledge_edges` 加 `review_status`（`pending/approved/rejected`，默认 `pending`）、`reviewed_by`（FK `users.id`，`ON DELETE SET NULL`）、`reviewed_at`；CHECK `ck_knowledge_edges_reviewed` 保证「非 pending 必须有 reviewed_at」。**AI 推断的边一律先进 `pending`**，人工通过才算数；`contains` 结构边由系统自动 `approved`（`reviewed_by` 留空）。迁移把历史行回填为 `approved`，避免上线瞬间整图变待校验。
- 决策 2（四类关系的生成方式）：`contains` 纯结构（父子，节点数 − 1，零成本）；`prerequisite` 走「向量召回 top-8 候选 + 每节点一次 LLM 判定（≤2 条、confidence ≥0.5、必须在候选内）」；`related`/`confusable` 走「余弦分档 + 批量 LLM 复核（每批 8 对）」。分档阈值：related `cos ∈ [0.75, 0.90)` 且不同父；confusable `cos ≥ 0.90` 或同父 `cos ≥ 0.75`；一对只进一个桶，confusable 优先。**阈值是拍出来的**（108 个知识点的样本），换 embedding 模型需重标定。
- 决策 3（候选排除规则，验收后补）：前置候选排除「自身 / 父子 / 同名节点」；related/confusable 候选排除「祖先-后代」。理由：不同章节的同名节点余弦≈1 但只可能是易混；上下级关系已由 `contains` 表达，再挂相关/易混只是噪音——真机 234 条待校验边里 34 条是这类章→子节边。
- 决策 4（幂等与墓碑）：已 `approved` 的边重跑时跳过（**永不降级**）；已 `rejected` 的边当墓碑跳过、不复活（本卡不做恢复入口）；`pending` 只刷新 `weight`；缺失才插入。前置方向守卫：已落库的反向对 + **本轮已计划的反向对**都要拦（后一条是验收补的，否则同轮 A→B、B→A 会同时落库）。
- 决策 5（成本与超时）：单次构建最多 **180 次 LLM 调用**（`MAX_CALLS`），用尽即停并标 `truncated=true`，任务仍算 `succeeded`。真机实测 108 知识点走完 144 次、~490 s，因此 `task_job_timeout_seconds` 默认 **300 → 1800**（ARQ 0.28 不支持按任务设超时，只能全局调）。
- 决策 6（审核与事务）：5 条接口全部 `require_role("admin","teacher")`；`/graph/edges/review` 必须注册在 `/graph/edges/{edge_id}/review` 之前。**审核用例自带 commit**——路由的 `get_db` 只 close 不 commit，验收时踩过「接口返回 updated=156、重新查询全是 pending」的静默丢数据。
- 决策 7（分页稳定性，验收后补）：`created_at` 在同一次构建里完全相同，只按它排序会让「同一行跨页重复 + 另一行漏掉」（实测 234 行里 19 行重复）。列表排序一律追加 `id` 兜底。
- 决策 8（人工校验口径）：任务卡要求 ≥30 条人工校验，本次做 **200 条**（157 通过 / 43 驳回），全部由**开发者逐条判定**，驳回逐条给理由（`review_rubric.py` / `decisions_reasons.json`）。**明确不是真实教师校验**，`reviewed_by` 指向验收账号（`user.id=60`），PROGRESS 与证据文档都标注「开发者自查」。
- 决策 9（已知随机性）：配对复核走 LLM，同 subject 重复构建会带来新增候选（本次重跑 pending 29 → 50，边数 336 → 357）。产品口径因此定为「**构建 = 补充候选，审核 = 人来定稿**」，不是一次构建就定稿。
- 测试与契约：后端基线 1082 → **1142 passed, 1 warning**；前端 194/35 → **204 passed / 36 files**；`API.md` 新增 §4.5 五条接口、`SCHEMA.md` 补三列 + `llm_call_logs.scene` 加 `graph`。
- 已知限制：关系语义靠 LLM，方向错与关系类型错都出现过（43 条驳回里 21 条是前置类）；阈值未按学科标定；`rejected` 无恢复 UI；图谱可视化与「按前置推荐」归 S4-6；浏览器级 E2E 未做（无 Playwright，§2.1 不擅自加依赖）。

## D-049 图谱可视化前端（S4-6）

- 背景：S4-5 把 357 条边落库并人工校验出 264 条 `approved`，但学生端看不到图。spec/plan 见 `docs/spec/s4-6-graph-view.md`、`docs/plan/s4-6-graph-view.md`。
- 决策 1（两个只读接口，不做前端拼装）：新增 `GET /kp/graph/snapshot?subject_id=` 一次给「节点 + approved 边 + 统计」，`GET /kp/graph/nodes/{kp_id}` 给详情（面包屑、四类邻居、本人笔记与错题）。理由：前端若靠 `/graph/edges` 分页拼全图，108 节点要翻 3 页且拿不到 `exam_weight`/`mistake_count`，首屏必然超 3s；详情按需请求才能把首次负载压在 170 ms。`Depends(get_current_user)`（学生也能看）——图谱结构不是隐私，隐私在笔记/错题，那部分额外按 `user_id` 过滤。
- 决策 2（只出 `approved`）：快照与详情都只返回 `review_status='approved'` 的边，`pending` 只以 `stats.pending_edges` 计数暴露（老师端提示「还有 N 条待校验」）。理由：未审核的 AI 边直接画进学生图谱等于把猜测当知识。
- 决策 3（`contains` 默认不画）：107 条父子边占 approved 的 40%，全画会把力导向拉成放射状、把真正的 157 条关系边挤到边缘。默认只勾「前置 / 相关 / 易混」，工具栏保留「结构（章→节）」开关。
- 决策 4（配色是**临时热力**，不是掌握度）：节点颜色 = 当前用户在该知识点下的错题数（0 灰 `#9aa4b2` / 1–2 黄 `#f0b429` / ≥3 红 `#e5484d`），页头明写「临时指标，S4-7 换真实掌握度」。真机发现：教师验收账号（id=60）108 个节点全灰，有错题的学生账号（id=50）是 103 灰 + 5 黄 —— 所以演示要用学生账号。节点大小 = 考纲权重 `round(8+22*clamp(w,0,1))`，权重缺失取下限 8。
- 决策 5（依赖与引入方式）：新增 `echarts@6.1.0`（已确认的依赖新增），按需引入 `echarts/core` + `GraphChart` + `TooltipComponent` + `CanvasRenderer`，不引全量包。理由：全量 echarts 进首屏 ≈ +500 KB，按需后构建产物单独成 chunk。
- 决策 6（>300 降级）：节点数超 `DEGRADE_THRESHOLD=300` 自动只画「焦点 + 一跳邻居」，横幅提示并给「显示全部（可能卡顿）」。焦点优先取用户当前选中节点，否则取**错题最多**的节点（避免首屏空白）。当前学科 108 节点不触发；阈值临时降到 20 时真机走通（nodes 5 / edges 8 / degraded true）。
- 决策 7（力导向不固定、不记忆位置）：不落库节点坐标、不做 sticky layout。理由：布局属于渲染细节，存库会带来「换屏幕尺寸后坐标错乱」和一张新表的成本；代价是每次刷新形态不同，接受。
- 决策 8（纯函数层单独可测）：把「可见集合 → ECharts option」抽成 `web/src/views/kp/useGraphData.ts`（颜色/大小/边样式/章归属/折叠/降级/搜索/option），页面只留请求与交互。理由：jsdom 没有 canvas，页面级测试只能 mock ECharts；抽出纯函数后 14 条用例直接断言颜色分档、降级子图、折叠后边过滤等易错逻辑。
- 决策 9（诚实空态）：`description` 全库为 NULL、`note_kps` 只有 2 行，页面不做任何补写，直接显示「暂无描述」「暂无关联笔记」。理由：§6 禁止编造数据。
- 测试与契约：后端基线 1142 → **1159 passed, 1 warning**；前端 204/36 → **225 passed / 39 files**；`npm run build` 退出 0。`API.md` §4.5 新增两条接口；`SCHEMA.md` §3.2 补读取口径旁注（无迁移，`alembic heads` 仍 `0012_s4_5`）。
- 已知限制：浏览器内交互未截图（无 Playwright，§2.1 不擅自加依赖），力导向观感、点击、折叠、首屏 <3s 需人工确认一次；掌握度仍是错题数代理；侧栏笔记/错题各限 20 条无「查看更多」；错题状态直接透中文枚举未做颜色区分；「按前置推荐」归 S4-7。

## D-050 掌握度模型与更新服务（S4-7）

- 决策 1（公式照方案 §6.6，纯函数内核）：`K_eff=K0/difficulty`、`M ← clamp(M+K_eff(s−M),0,1)`、`S` 答对 ×1.8 / 答错 ×0.5（限 1–60）、`M_t=M·e^(−Δt/S)`、`interval=clamp(round(S·M_t),1,30)` 天。全部写成 `app/services/mastery_service.py` 的纯函数（`MasteryState` 不可变 dataclass），DB 层只做「读行 → 算 → 写回」。理由：四条验收场景（答对提升/答错下降/长时不练衰减/连对间隔变长）能脱离数据库断言，答辩时能手推。
- 决策 2（参数是工程取值，不是拟合结果）：`K0=0.35`、×1.8/×0.5、上限 60 天来自「参考 SM-2 / FSRS 的简化」，没有用真实学生数据拟合；用 `scripts/mastery_sim.py` 的 3×3 敏感性扫描证明结论（连对掌握度上升、间隔变长）不依赖某一组精确参数。答辩口径必须照此说明，不能宣称"训练出来的参数"。
- 决策 3（懒创建 + 无行=未评估）：只为产生过作答事件的知识点建行，初始 `M=0`，不为 108 个知识点灌 0 行。理由：0 掌握和"没学过/没数据"是两件事，前端必须能区分（灰色 vs 红色）；也避免大批无信息行污染列表。
- 决策 4（挂载点只在错题复习）：`POST /mistakes/{id}/review` 同事务更新该题挂的**全部**知识点（`question_kps` 扇出），`correct=True → s=1`、`False → s=0`，难度取 `questions.difficulty`。`PATCH /mistakes/{id}` 的手动状态修改**不**写掌握度——手动改状态不等于真答对，否则掌握度会被改成假高。同事务而非补偿：掌握度写失败就让复习一起回滚，宁可 500 也不留不一致状态。
- 决策 5（`recompute` 回放语义）：`POST /kp/mastery/recompute` 按 `last_review_at or created_at` 时间序回放本人全部错题，状态折算 `待订正 0 / 已订正 0.5 / 已掌握 1`，**覆盖式重建**（先删本人全部行）。一条错题挂 K 个知识点产生 K 次同类事件；无 `question_kps` 的错题只计入 `skipped_no_kp`，不猜。幂等（真机跑两次结果一致）。理由：S5-4 的 `answers` 表还没建，先用错题历史把冷启动数据撑起来；覆盖式重建保证口径变化后能一键对齐，不留历史包袱。
- 决策 6（半对 `s=0.5` 的处置）：方案只给了答对/答错两条规则，半对按「不增强也不削弱记忆」处理——`S` 不变、`correct_cnt` 不加。当前半对只会在 `recompute` 回放「已订正」时出现，复习接口只有对/错两态。
- 决策 7（图谱配色换真实掌握度）：兑现 D-049 的「S4-7 换真实掌握度」——快照节点加 `mastery`（折算后 `M_t`，无行 `null`），前端四档 `<0.4 红 / 0.4–0.7 黄 / ≥0.7 绿 / null 灰`；`mistake_count` 保留但不再参与配色，仍用于详情侧栏与「焦点节点」挑选。
- 决策 8（精度与舍入）：`mastery NUMERIC(4,3)`、`stability NUMERIC(6,2)`，写入前用 `Decimal(str(x))` 定型，不靠 PG 隐式转换；公式内部 `round` 到入表精度再参与下一步，保证「手推 = 库里值 = 测试断言」三者一致。`effective_k` 对越界难度收敛到 1..5，不让脏数据炸掉公式。
- 决策 9（只读接口先给本人）：`GET /kp/mastery` 仅 `student` 且仅本人，支持 `subject_id`/分页/白名单排序（默认 `mastery ASC` 最薄弱优先，`sort_by=mastery` 同值多时按 `kp_id` 兜底）；老师/家长看学生掌握度留给 S4-8 的权限设计。
- 测试与契约：后端 1159 → **1186 passed, 1 warning**；前端 225 → **226 passed / 39 files**；`npm run build` 退出 0；`alembic heads` = `0013_s4_7`。`API.md` §4.6 新增两条接口 + §4.5 快照补 `mastery`；`SCHEMA.md` §6.3 补三处口径（精度、初始 M=0、懒创建）。
- 已知限制：浏览器内配色观感/tooltip 未截图（无 Playwright）；当前只有错题复习一个更新入口，S5-4 试卷作答、S5-5 清单完成需另接 `record_attempts`；真实账号里 34 条错题只有 3 条挂了知识点，所以演示时"掌握度有值"的知识点很少——这是知识对齐覆盖率问题，不是掌握度模型的问题。

## D-051 错题统计看板（S4-8）

- 决策 1（新开接口，不复用 `/mistakes/stats`）：看板走 `GET /api/v1/stats/overview`（`api/v1/stats.py`），S4-2 的三条小统计原样保留。理由：`/mistakes/stats` 的定位是「错题页顶部三个数组」，加趋势/掌握度/解释性计数会让它变胖，错题页还要为拿不到的字段买单；两者口径写在一起可交叉核对（实测同窗口下 total 33/1/0、by_cause 7 类、top_kps 5 条逐项一致）。代价是两条接口都要维护「窗口 → 统计」的相似 SQL，接受。
- 决策 2（`mastered` 是回算累计，不是历史快照）：`trend[].mastered` = 「当前状态=已掌握 且 `last_review_at` 不晚于该天」的错题数，窗口开始前的计入累计起点。理由：没有状态变更历史表，S5-4 的 `answers` 表还没建；硬造一张"事件历史表"超出本卡范围。代价：错题状态回退时历史曲线会跟着变低，API.md 与页面上都要写明。**这不是精确的历史序列，答辩时不能说「每天掌握多少」**。
- 决策 3（窗口与分桶一律 UTC）：窗口 `[今天-N+1 天 00:00 UTC, 现在]`，`date_trunc('day', …)` 依赖连接时区（全站 UTC）。理由：与全站存储/输出口径一致；代价是中国用户看到的"今天"差 8 小时，凌晨 0–8 点新增的错题会落到前一天——已写进 spec §8 已知限制。
- 决策 4（`range` 只给三档）：`7d|30d|90d`，默认 `30d`，非法值由 FastAPI `Literal` 拦成 422/42200，service 层再兜一层 `InvalidParamError`。理由：三档覆盖「近期订正/月度复盘/学期趋势」，自定义区间等真有需求再加，否则要处理任意窗口的补零与性能。
- 决策 5（TOP 柱少且等高，如实呈现）：真实数据里 34 条错题只有 3 条挂知识点（5 个 KP），所以柱图是 5 根、每根 `count=1`。看板不补假数据，而是返回 `summary.with_kp` 并在柱图下提示「其余 31 条错题没有关联知识点」。理由：§6 禁止编数据；这个数字同时是最有力的「知识对齐覆盖率低」证据。要改善得回看 S4-1 的对齐链路，不是改看板。
- 决策 6（掌握度四色提炼到 `utils/masteryColor.ts`）：S4-7 的四档配色原本写在 `views/kp/useGraphData.ts`，看板要第二份。提炼成 `web/src/utils/masteryColor.ts` 的 `masteryColor()` / `masteryLabel()`，图谱侧 `nodeColor` 改为委托（导出名保留）。理由：同一套口径两处硬编码必然漂移；图谱 13 条用例在委托后仍全绿。
- 决策 7（图表逻辑抽纯函数）：与 S4-6 同理，`views/stats/useStatsCharts.ts` 承接「数据 → option」（补零、`unknown` 灰、掌握度分档、`mastered` 全 0 不画线），页面只留请求/切档/`setOption`。jsdom 没有 canvas，只有纯函数能直接断言。
- 决策 8（骨架屏重建 DOM 后必须重绑实例）：真机实测「切窗口 → `canvas 数量: 0`」——`v-if="loading"` 把图表容器整棵重建，旧 ECharts 实例绑在已销毁节点上，`setOption` 无效。改为 `syncCharts()`：每次加载（`loading=false` 之后 + `nextTick`）按当前节点重绑，同一节点复用、不同则 `dispose` + `init`。mock 的 `init` 也补上 `getDom`，否则测不出这个行为。
- 决策 9（老师/家长视角仍未做）：D-050 决策 9 写过「老师/家长看学生掌握度留给 S4-8 的权限设计」，本卡任务卡与学生本人看板为先，**没有兑现**这条交叉引用；`/stats/overview` 明确只服务 `student` 本人。要支持教师视角需另开卡（涉及 `require_student_access`、班级/绑定关系与聚合口径），不在本卡偷偷加。
- 测试与契约：后端 1186 → **1201 passed, 1 warning**；前端 226/39 → **244 passed / 41 files**；`npm run build` 退出 0；`alembic heads` 仍 `0013_s4_7`（无迁移）。`API.md` 新增「统计看板（S4-8）」并给 `/mistakes/stats` 加交叉引用备注；`SCHEMA.md` 无变更。
- 已知限制：趋势只有 1 个非零点、`mastered` 全 0（真实数据形态）；`mastery` 只有 5 个知识点有值，看板能看到的掌握度样本很少；移动端窄屏未做响应式；老师/家长视角未做。

## D-052 列表里的公式渲染（S4-1/S4-2 小修）

- 决策 1（KaTeX 行内渲染，不用 MdPreview）：题干/摘录列表里把 `$…$`、`$$…$$` 直接渲染成公式，新组件 `web/src/components/common/MathText.vue` + 纯函数 `web/src/utils/mathText.ts`。不用现成的 `MdPreview`（md-editor-v3）：它是整块预览组件，20 行列表各挂一个太重，还会带回一整块编辑器样式；列表只需要行内公式。
- 决策 2（非公式片段必须转义）：题干来自用户上传/LLM，`v-html` 之前先 `escapeHtml`（`& < > " '` 五个字符），KaTeX 走 `throwOnError:false`、`trust:false`、`output:'html'`。写坏的公式（未闭合、非法命令）退化成转义后的原文，不抛到页面、不白屏。
- 决策 3（列表不做 JS 截断，交给 CSS）：原来 `stem_md.slice(0, 40)` 按字符切会把公式切成半条，KaTeX 无从渲染。改为整段渲染 + `-webkit-line-clamp: 2` 折行截断，完整题干放 `title`/tooltip（tooltip 里同样渲染，不露 `$`）。
- 决策 4（错题选题弹窗一起改）：同一症状共三处（`ReviewView` 题库列表、`MistakeListView` 错题列表、`MistakePickDialog` 选题弹窗），同一个组件的三行改动，一次改完；不顺手改其它模块。
- 测试与契约：新增 `utils/mathText.spec.ts`（8 条）与 `components/common/MathText.spec.ts`（6 条），并在题库/错题列表用例里各加一条「列表里必须出现 `.katex` 且文本不含 `$`」的回归断言；前端 244 → **258 passed / 43 files**，`npm run build` 退出 0；后端无改动。
- 已知限制：只处理 `$`/`$$` 两种定界符，不支持 `\(…\)`/`\[…\]`（当前题库与错题数据全是 `$` 风格）；行内公式多行折行时断行位置由浏览器决定，不做公式内断行控制；移动端窄屏仍未验证。

## D-053 题库列表的归属徽标与列调整（S4-1 小修）

- 决策 1（删掉 ID 列）：列表里的 `ID` 对使用者没有决策价值（不能搜、不能排序、点击题干才是入口），省下的 64px 给题干；`#id` 仍可在右侧详情头部看到，调试/引用不受影响。
- 决策 2（`我的` / `他人` 两态徽标，判断在纯前端）：`created_by === auth.user.id` → 蓝色 `我的`，否则灰色 `他人`。不新增接口：`QuestionSummary.created_by` 字段本来就有。徽标表达的是**归属**而不是"能否编辑"——老师/管理员能改所有人的题，所以不写成 `可编辑 / 只读`，避免对学生与老师呈现两种含义。他人的题仍然可看、可被错题引用，只是保存/删除按钮禁用（原有 `canEdit` 逻辑未动）。
- 决策 3（列名 `来源` → `答案来源`）：该列显示的是 `verified`（`卷面` / `AI/无`），即"答案从哪来"，原来叫「来源」容易被误读成"题目从哪来"。只改列名，取值与判定不变。
- 决策 4（不做「只看我的」筛选）：服务端分页下前端过滤只能过滤当前页，是错的做法；要做必须给 `GET /questions` 加 `created_by` 参数（接口变更 + API.md + 测试）。任务卡没要求，本卡不做，需要时单独提。
- 验证：`ReviewView.spec.ts` 新增 2 条（`ID` 列消失、徽标两态、`答案来源` 列名），前端 258 → **260 passed / 43 files**，`npm run build` 退出 0；真机（学生 50，Chrome headless 读 DOM）三页徽标合计 34 `我的` + 21 `他人`，与库里 `created_by` 分布（50→34 / 36→20 / 46→1）一致。

## D-054 知识点挂不上时不强取「最接近」（S4-1 决策留档，不实现）

- 背景：55 道题库里 34 道没有知识点（全是解答题，题干中位 31 字）。用户提出「取一个最接近的应该没问题」。查证结论：**不采用**。
- 实测（2026-11-05，纯向量计算 0 次 LLM 调用）：34 道空题各自的向量 top1 余弦最小 0.411 / 中位 0.552 / 最大 0.781；top1 与 top2 的差距多数 <0.02（0.001–0.067），说明"最接近"在向量空间里并不显著。抽看 12 条：4 条合理（对称轴→一元二次函数、1/x 单调性→函数的单调性、解一元二次方程→一元二次方程、等比数列前 5 项和→前 n 项和），8 条明显错（∫₀¹(2x+1)dx→基本求导公式、化简 (a+b)²-(a-b)²→二倍角公式、a=3,b=-2 求 a²-b→函数零点与二分法、涨价降价→分类加法计数原理）。
- 两个根因：① 考纲只有 108 个知识点，**本身缺条目**（无定积分、无乘法公式、无纯算术练习类）；② 这批题是短算式，"没有对应知识点"是事实而非缺陷。
- 决策：**保持宁缺毋滥**，不自动取 top1。理由：错标签比空标签危害大且不可见——掌握度会按错知识点升降、看板 TOP10 指向错章节、复习推荐推错题，而用户没有手段发现。空标签至少是诚实的"未对齐"。
- 若将来要救（备选口径，未实现）：`cos ≥ 0.55` **且** top1-top2 `gap ≥ 0.02` 才自动挂（34 题中可覆盖 11 条，抽样质量明显优于无条件 top1），`question_kps` 增 `source` 列标 `inferred`，前端灰 tag「AI 推测」；护栏外的题给「挂知识点」快捷入口（候选即现成 top-10）。两项都需要迁移/交互，本次确认不做。
- 影响：看板「知识点 TOP10」只有 5 根柱、掌握度样本少，是知识对齐覆盖率问题，不是统计或掌握度模型的问题；已在 PROGRESS 与 S4-8 验收证据里如实记录。

## D-055 看板 TOP10 加掌握度颜色图例（S4-8 小修）

- 背景：真实数据下 TOP10 柱图是「5 根等长横条、全红」，用户看不出柱色代表什么（只有 tooltip 里有掌握度数字）。等长是数据事实（34 条错题只有 3 条挂知识点，命中 5 个知识点各 1 条），全红也是事实（掌握度 0.347/0.000/0.347/0.141/0.347 全 <0.4）；问题在**颜色没有图例**，不在数据。
- 决策：只加图例，不改图形语义、不改统计口径、不补数据。图例由纯函数 `masteryLegendItems()` 产出（顺序 `<0.4` / `0.4–0.7` / `≥0.7` / `未评估`），颜色直接取 `utils/masteryColor` 的四个常量，与图谱同一口径；页面渲染成标题下的一行色块 + 文案（`data-testid="top-kp-legend"`），空态（没有挂知识点的错题）时不显示。
- 明确没做的事（讨论过、用户选择不做）：① 「最大 count ≤ 2 时加一行说明文案」；② count 全为 1 时改画掌握度横条；③ TOP10 换成表格。理由：用户只需要图例，其余属于设计偏好，不擅自加。
- 验证：`useStatsCharts.spec.ts` 新增 2 条（图例内容/顺序、颜色与 `masteryColor` 分档一致），`Stats.spec.ts` 新增 1 条（页面渲染 4 项且空态不渲染）；前端 260 → **263 passed / 43 files**，`npm run build` 退出 0；真机（学生 50）实测图例文本 `‹0.4 / 0.4–0.7 / ≥0.7 / 未评估`、色块 `rgb(229,72,77)/rgb(240,180,41)/rgb(34,197,94)/rgb(154,164,178)`、三块画布仍在。

## D-056 错因饼图改为枚举固定配色（S4-8 缺陷修复）

- 缺陷：`causeColor()` 原来用「错因名哈希 → 6 色调色板」，6 类错因实测压成 3 种颜色（概念不清/时间不足 同红，计算失误/审题偏差 同橙，知识遗忘/方法不当 同绿），饼图相邻扇区同色无法区分。哈希在 6 色上必然高概率撞色，这是设计错误而非参数没调好。
- 决策 1（枚举一一映射）：错因是 S4-3 定义的**有限枚举**（6 类 + unknown），直接写死映射：概念不清 `#e5484d` / 计算失误 `#f0b429` / 知识遗忘 `#8b5cf6` / 方法不当 `#3b82f6` / 时间不足 `#14b8a6` / 审题偏差 `#f97316` / unknown 灰 `#9aa4b2`。确定性、可预测、扩展新错因时一眼知道要不要补色。
- 决策 2（意外名字兜底）：枚举之外的名字（理论上不该出现）按 `EXTRA_CAUSE_COLORS` 顺序取当前图未用的颜色，`causeColors(data)` 维护已用集合，保证**同一张饼没有两个同色扇形**。
- 决策 3（图例与扇形同色）：原来只在 `series.data[i].itemStyle` 设色，ECharts 的 legend 是否跟随不可靠；现在显式给 `legend.data` 里每项带 `itemStyle.color`，避免「图例色块骗人」。
- 验证：`useStatsCharts.spec.ts` 新增 3 条（6 类两两不同色、图例与扇形同色、意外名字不撞色），前端 263 → **266 passed / 43 files**，`npm run build` 退出 0；真机（学生 50）对 `/stats` 饼图画布做像素采样，出现 7 种主色且与映射表逐一对应（`229,72,77` / `240,180,41` / `139,92,246` / `59,130,246` / `20,184,166` / `249,115,22` / `154,164,178`）。

## D-057 侧栏导航去掉序号（全局 UI 小修）

- 背景：侧栏每个导航项前有 `01`–`09` 装饰序号，用户明确表示不要。
- 决策：从数据层删掉，而不是仅隐藏——`layouts/nav.ts` 的 `NavItem` 去掉 `index` 字段（没有任何其他地方读它），`SideNav.vue` 删掉序号 `<span>` 与 `.nav-index` 样式，`.nav-link` 的单子元素不再需要 `gap`。理由：只留一个不渲染的字段，半年后没人知道它为什么在；序号本来就是纯装饰，删掉不留技术债。
- 验证：`MainLayout.spec.ts` 新增 1 条（首个导航项文本恰为「笔记」、`.nav-index` 不存在、不出现 `01`）；前端 266 → **267 passed / 43 files**，`npm run build` 退出 0；真机（学生 50）实测 9 项文本与 `.nav-index` 数量为 0。
- 影响面：只有导航外观，路由 `meta.nav` 与 `data-testid` 未动，其它页面无感知。
