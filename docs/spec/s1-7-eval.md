# S1-7 自测用例与效果抽查 spec

- 任务卡：`docs/AI协作开发实施计划.md` §S1-7（20–30 条自测问答 + 抽查脚本，拿到第一组真实数字）
- 日期：2026-10-20
- 状态：设计已确认，待用户审阅本 spec 后写 plan
- 上游：S1-5 检索/Rerank、S1-6 带引用回答与拒答
- 产物：`eval/datasets/qa_set.jsonl`、`eval/configs/*.json`、`eval/qa_eval.py`、`eval/run.py`、`eval/results/*`、`docs/EVAL_S1.md`

## 1. 目标

用一套**用户确认 gold** 的固定问答集，回答三个问题：

1. 纯向量、RRF 混合、混合+Rerank 三种检索配置在 top5 上的真实差距；
2. S1-6 回答链路的引用是否指向人工认定的正确块，拒答是否判对；
3. 单次问答的平均延迟、token 与费用，给论文第 6 章一组可复现数字。

## 2. 范围

### 2.1 做

- 定义 `qa_set.jsonl` 格式、校验规则、候选块标注流程；
- 三份检索配置 JSON；
- `eval/qa_eval.py`：加载、校验、指标纯函数；
- `eval/run.py`：按配置跑检索；对生产配置跑完整回答；
- JSON + Markdown 结果输出；
- `docs/EVAL_S1.md`：真实结果、失败题、与 S1-5 的差异、局限；
- 验收通过后打本地 tag `m0-rag-validated`。

### 2.2 不做

- 不生成“标准答案”；gold 最终必须由用户确认，实际采用 AI 预标注 + 用户确认（§3.3/§15）；
- 不做答案文本的语义正确性评分（没有标准答案；本卡只测引用/拒答）；
- 不改 S1-5 的检索算法、不改 S1-6 的 Prompt/阈值；
- 不建 API/数据库表/迁移，不引入新依赖；
- 不把纯向量/混合配置送去 LLM 重复生成回答；
- 不把合成样张或临时问题说成真实学生数据。

## 3. 数据集

### 3.1 规模与构成

固定 **30 条**：

- 20 条应答题：`should_refuse=false`，`gold_chunk_ids` 至少 1 个；
- 10 条应拒题：`should_refuse=true`，`gold_chunk_ids=[]`。

问题覆盖现有 7 个 note（101–107），并保留 S1-5 的 10 个问题作为回归子集。候选问题清单：

| # | question | scope | 类型 |
|---|---|---|---|
| q001 | 函数的定义域怎么求？ | 函数 | 应答题 |
| q002 | 函数单调性的定义是什么？ | 函数 | 应答题 |
| q003 | 如何用定义证明函数在区间上单调递增？ | 函数 | 应答题 |
| q004 | 奇函数和偶函数有什么性质？ | 函数 | 应答题 |
| q005 | 二次函数在闭区间上的最值怎么求？ | 函数 | 应答题 |
| q006 | 分段函数 f(f(-1)) 怎么求？ | 函数 | 应答题 |
| q007 | 函数 f(x)=x+1/x 在 (1,+∞) 上的单调性如何证明？ | 函数 | 应答题 |
| q008 | 已知奇函数在 x≥0 时的解析式，怎么求 x<0 的解析式？ | 函数 | 应答题 |
| q009 | 函数图象关于原点对称说明什么？ | 函数 | 应答题 |
| q010 | 商品定价最大利润问题怎么建模？ | 函数 | 应答题 |
| q011 | 指数函数的定义域和值域是什么？ | 指对函数 | 应答题 |
| q012 | 对数函数的定义域和值域是什么？ | 指对函数 | 应答题 |
| q013 | 指数式 a^b=N 和对数式怎么互化？ | 指对函数 | 应答题 |
| q014 | y=log_0.5(x^2-2x-3) 的单调区间怎么求？ | 指对函数 | 应答题 |
| q015 | 导数大于 0 说明函数在区间上什么性质？ | 导数 | 应答题 |
| q016 | 函数 f(x)=x^3-3x 的单调区间是什么？ | 导数 | 应答题 |
| q017 | 函数 f(x)=x ln x 的极小值是多少？ | 导数 | 应答题 |
| q018 | 等差数列 a_1=2，d=3，a_10 等于多少？ | 数列 | 应答题 |
| q019 | 等比数列 a_1=1，q=2，前 5 项和 S_5 是多少？ | 数列 | 应答题 |
| q020 | 错位相减法的口诀是什么？ | 数列 | 应答题 |
| q021 | 今天北京天气怎么样？ | 无关 | 应拒题 |
| q022 | 怎么用 Python 写一个网页爬虫？ | 无关 | 应拒题 |
| q023 | 《红楼梦》的作者是谁？ | 无关 | 应拒题 |
| q024 | 出国留学需要准备哪些材料？ | 无关 | 应拒题 |
| q025 | 今天股市行情怎么样？ | 无关 | 应拒题 |
| q026 | 如何做番茄炒蛋？ | 无关 | 应拒题 |
| q027 | 世界杯冠军是谁？ | 无关 | 应拒题 |
| q028 | 电脑蓝屏怎么修？ | 无关 | 应拒题 |
| q029 | 怎样提高英语听力？ | 无关 | 应拒题 |
| q030 | 汽车轮胎多久换一次？ | 无关 | 应拒题 |

### 3.2 JSONL 格式

一行一个 JSON 对象，UTF-8，无 BOM：

```json
{"id":"q001","question":"函数的定义域怎么求？","scope":"函数","gold_chunk_ids":[123],"should_refuse":false}
{"id":"q021","question":"今天北京天气怎么样？","scope":"无关","gold_chunk_ids":[],"should_refuse":true}
```

> `[123]` 只是格式示意，不是本数据集的 gold；真实值必须由用户勾选后写入。

字段：

| 字段 | 类型 | 规则 |
|---|---|---|
| `id` | string | 非空，唯一，建议 `qNNN` |
| `question` | string | 去空白后非空 |
| `scope` | string | 非空；可用“函数/指对函数/导数/数列/无关” |
| `gold_chunk_ids` | int[] | 正整数、去重；应答题至少 1 个；应拒题必须为空 |
| `should_refuse` | bool | 必填 |

### 3.3 标注/确认流程（实际执行）

1. 实现者生成 `eval/datasets/qa_set.candidates.md`：每题列 fused top10 候选块，并附全量 83 块目录（`chunk_id / note_id / heading / 100 字片段`）；
2. 用户因逐题勾选成本过高，同意改为 **AI 预标注 + 用户确认**：AI 先按 chunk 内容提议 gold，用户确认/修改；
3. 实现者只把用户确认后的 ID 写入 `qa_set.jsonl`；用户未确认的版本不进入正式数据集；
4. 如果用户认为某题语料里没有可答内容，改为应拒题或换题；不硬凑 20 条；
5. 候选中出现的真实校名/命题人必须脱敏为“某学校/某老师”；最终 JSONL 只存 ID，不存正文。
6. 该方式存在选择偏差（候选清单参考检索结果），文档必须写明，不得宣称纯人工标注。

### 3.4 校验规则（加载即校验）

`load_dataset(path)` 必须拒绝：

- 文件不存在、空文件、任一行非 JSON 对象；
- 缺字段、类型错误、`id` 为空或重复；
- `question/scope` 去空白后为空；
- `gold_chunk_ids` 含 0/负数/重复；
- `should_refuse=false` 且 gold 为空；
- `should_refuse=true` 且 gold 非空；
- 条数不在 20–30；
- gold ID 在 `note_chunks` 中不存在，或不属于 `--user-id`。

错误信息带行号/ID；不做“跳过坏行继续”的静默容错。

### 3.5 与数据库的关系

- `gold_chunk_ids` 是 `note_chunks.id`（数据库主键），不是 `note_id` 或 `chunk_index`；
- 标注基于当前 83 块/7 note 语料；如果重切/重入库导致 ID 变化，数据集必须重新标注并记录版本；
- 运行开始时一次性查出该用户全部 `id -> note_id`，用于存在性/归属校验；禁止循环查库。

## 4. 配置

`eval/configs/<name>.json`，字段固定：

```json
{
  "name": "vector",
  "retrieval": "vector",
  "top_k": 20,
  "top_n": 5
}
```

```json
{
  "name": "hybrid",
  "retrieval": "hybrid",
  "top_k": 20,
  "top_n": 5
}
```

```json
{
  "name": "hybrid_rerank",
  "retrieval": "hybrid_rerank",
  "top_k": 20,
  "rerank_candidates": 30,
  "rerank_top_k": 6,
  "top_n": 5
}
```

规则：

- `retrieval` ∈ `vector | hybrid | hybrid_rerank`；
- S1-7 固定 `top_n=5`；`top_k>0`；rerank 的 `rerank_candidates/top_k` 为正且 `top_k>=top_n`；
- 配置名与文件名一致；`--config hybrid_rerank` 解析为 `eval/configs/hybrid_rerank.json`；
- 配置只控制检索；回答指标只在 `hybrid_rerank` 上计算（生产链路）。

### 4.1 三种配置的检索路径

| config | 调用 | 评估列表 | 延迟口径 |
|---|---|---|---|
| vector | `retrieve_hybrid()` 一次 | `result.vector[:5]` | `result.elapsed_ms`（含同次全文开销，偏保守） |
| hybrid | `retrieve_hybrid()` 一次 | `result.fused[:5]` | `result.elapsed_ms` |
| hybrid_rerank | `retrieve_hybrid_reranked()` | `result.reranked[:5]` | `result.elapsed_ms + rerank_info.latency_ms` |

> 纯向量配置复用同一次混合检索调用但只评估向量列表；延迟包含全文查询开销，论文中必须说明，不把它当成“纯向量独立延迟”。若后续要严格隔离，另开任务，不在本卡改 retriever。

## 5. 运行器架构

### 5.1 `eval/qa_eval.py`（纯逻辑，易测）

- `QACase(BaseModel)`：字段与 §3.2 一致；
- `RetrievalConfig(BaseModel)`：字段与 §4 一致；
- `load_dataset(path, *, min_items=20, max_items=30) -> list[QACase]`；
- `load_config(path) -> RetrievalConfig`；
- `hit_at_k(hits, gold_ids, k) -> bool`；
- `first_gold_rank(hits, gold_ids, k) -> int | None`；
- `citation_precision(cited_ids, gold_ids) -> float`；
- `citation_hit(cited_ids, gold_ids) -> bool`；
- `refusal_confusion(cases, results) -> dict`；
- `aggregate(...) -> EvalSummary`；
- 所有函数不读环境、不连数据库、不调外部 API。

### 5.2 `eval/run.py`（编排）

CLI：

```bash
python eval/run.py --dataset qa_set --config hybrid_rerank
python eval/run.py --dataset qa_set --config vector --skip-answer
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--dataset` | 必填 | `qa_set` 或 `.jsonl` 路径；无后缀时拼 `eval/datasets/<name>.jsonl` |
| `--config` | 必填 | 配置名或 `.json` 路径 |
| `--user-id` | 1 | 只查该用户语料 |
| `--skip-answer` | false | 只跑检索，不调用 LLM；rerank 配置默认跑回答 |
| `--output` | 自动 | JSON 路径；默认 `eval/results/s1-7-<config>.json` |
| `--md-output` | 自动 | Markdown 路径；默认同名 `.md` |

流程：

1. 加载并校验数据集/配置；
2. 查 `note_chunks` 的 `id -> note_id`，校验 gold 存在且属于 `--user-id`；
3. 对每条应答题，按配置检索，记录 top5、hit/MRR、延迟；
4. 若配置为 `hybrid_rerank` 且未 `--skip-answer`：调用 `answer_question()`，记录 refused/reason/引用的 chunk_id/引用精确率/引用命中/tokens/延迟/费用；
5. 聚合，写 JSON 与 Markdown；
6. 终端打印 Markdown 表格与关键数字。

### 5.3 数据流

```text
qa_set.jsonl ──校验──┐
                     ├─ 检索配置(vector/hybrid/rerank) ── top5 ── hit@5/MRR
note_chunks(id→user)─┘                                  │
                                                        └─ hybrid_rerank: answer_question
                                                           → refused / citations / tokens / cost
```

## 6. 指标

### 6.1 检索（应答题，n=20）

- `hit@5 = 命中任一 gold 的题数 / 20`；top5 为空或未命中均算失败。
- `MRR@5 = Σ(1/首个 gold 的排名) / 20`；未命中记 0。
- 命中判定用 `chunk_id` 精确匹配，不做正文模糊匹配。
- 拒答题不参与 hit/MRR（没有 gold）；单独看拒答。

### 6.2 引用（应答题，n=20；仅 hybrid_rerank）

- `citation_precision = |cited ∩ gold| / |cited|`；未引用/被拒答记 0；逐题平均。
- `citation_hit = 1` 当且仅当至少一个引用块 ∈ gold；被拒答/无引用记 0；逐题平均。
- `citation_chunk_ids` 全部来自 `AnswerResult.citations[*].chunk_id`。
- 额外记录 `citation_retry_count` 总和，不把重试隐藏。

### 6.3 拒答（全部 n=30）

- `refusal_accuracy = 判对题数 / 30`；
- 混淆矩阵：
  - TP：应拒且拒；
  - FP：不应拒却拒；
  - FN：应拒不拒；
  - TN：不应拒且答。
- 应拒但答出的，引用指标不参与平均（在逐题结果中标记 `citation_precision=null`）。

### 6.4 成本/延迟（仅 hybrid_rerank 回答）

- `avg_total_tokens`、`avg_latency_ms`、`total_cost_yuan`、`llm_calls`；
- token/cost 全部取 `AnswerResult` 实测字段，不估算；
- `avg_total_tokens`/`avg_latency_ms` 以全部 30 条为分母（应拒题未调 LLM，记 0），另外记录 `answered_count`；
- 检索配置的延迟另表记录。

## 7. 输出

### 7.1 JSON（`eval/results/s1-7-<config>.json`）

```json
{
  "dataset": "qa_set",
  "config": "hybrid_rerank",
  "user_id": 1,
  "generated_at": "2026-10-20T...",
  "case_count": 30,
  "answerable_count": 20,
  "refusal_count": 10,
  "retrieval": {
    "hit_at_5": 0.0,
    "mrr_at_5": 0.0,
    "avg_latency_ms": 0
  },
  "answer": {
    "citation_precision": 0.0,
    "citation_hit_rate": 0.0,
    "refusal_accuracy": 0.0,
    "confusion": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
    "avg_total_tokens": 0.0,
    "avg_latency_ms": 0.0,
    "total_cost_yuan": 0.0,
    "llm_calls": 0,
    "citation_retry_count": 0
  },
  "cases": []
}
```

- `answer` 在 `vector/hybrid` 或 `--skip-answer` 时为 `null`；
- `cases` 保留逐题证据：`id/question/should_refuse/refused/refusal_reason/hit_at_5/first_gold_rank/cited_chunk_ids/citation_precision/citation_hit/latency_ms/total_tokens/cost_yuan`；
- JSON 中不得出现 chunk 正文、Prompt、API Key、真实校名/姓名。

### 7.2 Markdown

终端与 `.md` 使用同一张表：

```markdown
| 配置 | hit@5 | MRR@5 | 引用精确率 | 引用命中率 | 拒答准确率 | 平均延迟 | 平均 tokens | 总费用 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hybrid_rerank | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0ms | 0.0 | ¥0.000000 |
```

- 不适用的单元格写 `—`；
- 终端必须打印数据集条数、配置名、真实数字和输出路径。

## 8. 错误处理

| 情况 | 行为 |
|---|---|
| 数据集格式/条数/重复 ID/gold 矛盾 | 退出码 2，打印行号/ID；不写结果文件 |
| gold ID 不存在或不属于 user | 退出码 2，列出缺失/越界 ID；不静默丢弃 |
| 配置未知/字段非法 | 退出码 2，打印可用配置 |
| 数据库连接失败 | 退出码 3，提示启动 compose |
| Embedding/Rerank/LLM 错误 | 退出码 4，保留原始异常类型；不伪造结果 |
| `--skip-answer` 用在 vector/hybrid | 正常；answer=null |
| `--skip-answer` 用在 hybrid_rerank | 允许，但文档必须标明不是完整验收 |
| 某题检索为空 | 记录该题 hit=false/rank=null，继续；不崩 |
| 回答被拒/引用为空 | 记录 refused/reason；citation 指标按 0 处理；不伪造引用 |
| 网络/DB 中途失败 | 不写半成品 JSON（先聚合成功再落盘） |

## 9. 测试

全部 mock 外部调用，不访问真实 DB/网络。

### 9.1 数据集

1. 合法 30 条通过；
2. 少于 20 条报错；
3. 多于 30 条报错；
4. 重复 id 报错；
5. 缺字段/类型错误报错；
6. 应答题 gold 为空报错；
7. 应拒题 gold 非空报错；
8. gold 重复/非正报错；
9. 非法 JSON 行带行号；
10. 空文件/不存在文件报错。

### 9.2 配置

1. 三份配置都能加载；
2. `top_n != 5` 报错；
3. `retrieval` 非法报错；
4. rerank 配置 `rerank_top_k < top_n` 报错；
5. 未知配置报错。

### 9.3 指标

1. hit@5 命中/未命中/空列表；
2. MRR@5 第 1/第 3/未命中；
3. 引用精确率全中/部分/0/空；
4. citation_hit；
5. 拒答混淆矩阵 TP/FP/FN/TN；
6. 应拒题不进入 hit/MRR 分母。

### 9.4 运行器

1. `vector` 路由只评估 `result.vector`；
2. `hybrid` 路由只评估 `result.fused`；
3. `hybrid_rerank` 路由评估 `result.reranked`；
4. `--skip-answer` 不调用 answerer；
5. 默认 rerank 调用 answerer；
6. gold 不存在退出 2；
7. JSON/Markdown 写盘字段完整；
8. 中途异常不落盘半成品。

### 9.5 脚本冒烟

`python eval/run.py --help` 退出 0，不连库。

## 10. 验收

```bash
# 1. 数据校验 + 三配置检索
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config vector --skip-answer
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config hybrid --skip-answer
.venv\Scripts\python.exe eval/run.py --dataset qa_set --config hybrid_rerank

# 2. 全量测试
cd backend && ..\.venv\Scripts\python.exe -m pytest -q
```

通过条件：

- 数据集 30 条；gold 采用“AI 预标注 + 用户确认”，并记录该偏差，不写成纯人工标注；
- `hybrid_rerank` 的 `hit@5 >= 0.6`（20 条应答题至少命中 12 条）；不达标如实报告，回 S1-2 切片，不调问题粉饰；
- 引用/拒答指标有真实数字，拒绝为 0 时明确写 0；
- JSON/Markdown 落盘，终端输出可贴论文；
- `docs/EVAL_S1.md` 写清失败题、与 S1-5 的差异、样本量与局限；
- 全量 pytest 不回归。

## 11. 已知局限

- 只有 30 条、83 块/7 note，统计波动大；hit@5 容易饱和，不能外推真实学生规模。
- gold 是“块级相关性”，不判断答案句子是否被引用块逐字支持；citation precision 不等于答案正确。
- 纯向量延迟包含同次全文开销（§4.1），不是严格隔离的向量延迟。
- 回答指标只在 `hybrid_rerank` 上测，不能把差异归因给三种检索配置。
- 数据集 ID 绑定当前切片版本；重切后必须重新标注。
- 10 条拒答题是明显域外问题，真实用户会更难；拒答准确率偏乐观。
- 合成样张 note 107/106 不是真实学生数据，论文中必须标注。

## 12. 安全与隐私

- `qa_set.jsonl` 只存问题、scope、chunk ID；不存正文、姓名、学校、联系方式；
- 候选清单中的 headings 如含校名，统一脱敏为“某学校”；
- 结果 JSON 不含 Prompt、Key、chunk 正文；
- `.env` 不提交；日志只记计数/耗时/费用。

## 13. 文档同步

- `docs/PROGRESS.md`：S1-7 完成状态、真实数字、失败题；
- `docs/DECISIONS.md`：D-020 记录“回答指标只在生产配置上算”“gold 采用 AI 预标注 + 用户确认”等决策；
- `docs/EVAL_S1.md`：评测方法、数据、结果、复现命令；
- `AGENTS.md` §9.6：评测运行器锚点（如适用）；
- `eval/results/`：JSON/Markdown 真实输出；
- 无 API/SCHEMA 变更。

## 14. 自检

- [x] 目标/范围/不做事项明确
- [x] 数据格式、条数、gold 来源明确
- [x] 三配置与指标公式可测试
- [x] 失败路径和退出码明确
- [x] 测试全部 mock，真实验收单独跑
- [x] 隐私边界明确：只存 ID，不存正文
- [x] 与 S1-5/S1-6 的边界清楚
- [x] 无 API/SCHEMA/迁移/新依赖

## 15. 实施回填

- 实际测试数量：S1-7 新增 31 条（数据集/配置 16、指标 8、运行器 7）；全量 191 passed。
- qa_set：30 条（20 应答题 + 10 应拒题）。
- gold 来源：AI 预标注 + 用户确认；候选清单参考了 fused top10，存在选择偏差。
- 真实三配置：

| 配置 | hit@5 | MRR@5 | 引用精确率 | 引用命中率 | 拒答准确率 | 检索平均延迟 |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 0.917 | — | — | — | 198ms |
| hybrid | 1.000 | 0.827 | — | — | — | 197ms |
| hybrid_rerank | 1.000 | 0.938 | 0.827 | 1.000 | 100.0% | 440ms |

- `hybrid_rerank` 回答：平均延迟 6243ms、平均 tokens 945.5、总费用 ¥0.0317224、llm_calls 24、citation_retry_count 2。
- 与 plan 的偏离：
  - gold 原计划“用户手工勾选”，实际改为“AI 预标注 + 用户确认”；
  - 候选清单从 top5 扩为 fused top10 + 全量 83 块目录，避免 gold 不在 top5 时无法标注；
  - 指标测试一条断言由 `refusal_accuracy=1.0` 修正为 `2/3`，原测试数据包含一个 FP，断言写错（实现公式未改）。
- 已知问题：
  - `hit@5=1.000` 受 gold 预标注参考候选清单影响，不能外推；
  - q004/q005/q009 语料只有性质/例题，属弱证据题；
  - q026/q029 最终拒答正确但已调用 LLM，产生 1277/1235 tokens；
  - 引用精确率有 7 题低于 1.0，详见 `docs/EVAL_S1.md`。