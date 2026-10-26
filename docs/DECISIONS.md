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

## 待与导师拍板（方案附录 F 摘录）

| # | 决策项 | 备选 | 方案建议 | 状态 |
|---|---|---|---|---|
| 3 | 是否公网部署 | 公网 / 局域网 / 本地 | 先本地 + 局域网演示 | 已拍板 2026-10-15：仅本地（→D-009） |
| 4 | Agent 优先级 | 必做 / 选做 | 选做（M5） | 已拍板 2026-10-15：选做（→D-010） |
| 5 | 自测使用深度 | 偶尔用 / 持续自用 | 持续自用（每周记录） | 已拍板 2026-10-15：偶尔用（→D-011） |
| 7 | 学校对 AI 辅助编码的要求 | — | M0 就确认 | 已拍板 2026-10-15：允许（→D-012） |

> 已定项：#1 FastAPI（→D-001）、#2 数学（→D-002）、#6 软著不做（成果为答辩 PPT、演示视频与系统截图包）。
> 2026-10-15：附录 F 全部 7 项拍板完毕，决策悬空清零归档。
