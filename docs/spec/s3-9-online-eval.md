# S3-9 在线链路抽查与三配置对照

> 状态：待确认（设计已口头确认，本文为待确认 spec）
> 日期：2026-11-02

## 1. 背景与目标

S1-7 的评测是脚本层：直接调用 `retrieve_hybrid*` / `answer_question`，绕过 HTTP、鉴权、SSE 和真实 API 组装。S3-9 把抽查切到 API 层，用真实学生 token 调 `POST /retrieval/search` 与 `POST /qa/ask`，并产出：

1. 40 条人工标注的 M2 数据集；
2. 纯向量 / 混合 / 混合+rerank 三配置对照表；
3. 逐题“引用是否正确”“是否该拒答”核对材料；
4. `docs/EVAL_M2.md` 与可复现命令。

“API 层”指评测脚本不直接查数据库、不直接调检索/回答 service；所有检索与回答都经真实 HTTP 接口。数据库仍由后端服务访问。

## 2. 范围

### 2.1 做

- `/retrieval/search` 增加可选 `retrieval` 模式，覆盖三配置。
- `/qa/ask` 的 `done` 事件增加 `cost_yuan`（只读、向后兼容），用于真实费用。
- `eval/run.py` 增加在线模式、登录/ token 鉴权、`--config all`、40 条数据集校验、三配置对照输出。
- 新建 `eval/datasets/qa_set_m2.jsonl`（30 应答 + 10 应拒，当前 chunk ID）。
- 新建 `docs/EVAL_M2.md`，写方法、三配置表、逐题核对、失败解释、局限。
- 同步 API.md / PROGRESS / DECISIONS / 实施计划。

### 2.2 不做

- 不引入 RAGAS、浏览器 E2E、向量数据库或新依赖。
- 不改前端页面，不新增数据库表/迁移。
- 不把 S3-8 的 10 轮验收数据混入 M2 指标。
- 不做自动“答案数学正确性”判定；引用/拒答由逐条阅读核对。
- 不改 S1-7 数据集与历史结果；`qa_set.jsonl` 保留。
- 不自动打 tag，不自动 push；里程碑 tag 由用户在验收后决定。

## 3. 接口契约

### 3.1 `POST /api/v1/retrieval/search` 新增 `retrieval`

权限仍为 student。请求新增字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| retrieval | `vector` / `hybrid` / `hybrid_rerank` | 否 | 缺省时保持原行为：按 `rerank` 与 `RETRIEVAL_RERANK_ENABLED` 决定 |

语义与冲突规则：

- `retrieval` 缺省：完全保持 S3-2 行为；`rerank` 缺省读配置，`top_k` 缺省读配置。
- `retrieval=vector`：走向量结果，固定不重排；`rerank=true` 返回 422。
- `retrieval=hybrid`：走 RRF 融合，固定不重排；`rerank=true` 返回 422。
- `retrieval=hybrid_rerank`：走重排；`rerank=false` 返回 422。
- `retrieval` 与 `rerank` 不冲突时，以 `retrieval` 为准；不静默改写。
- 三配置的 `top_k` 仍为 1–20，评测固定 5。
- `vector` 仍复用 `retrieve_hybrid` 的向量召回后取前 `top_k`，不是独立纯向量 SQL；延迟口径偏保守，文档明确。
- 响应字段不新增；`rerank` 仍表示本次是否实际重排。

错误码：未知 `retrieval` / 冲突 422（同一套 42200）；鉴权与权限错误不变。

### 3.2 `POST /api/v1/qa/ask` 的 `done.cost_yuan`

`done` 增加：

```json
{"cost_yuan": 0.012345}
```

- 为本次回答所有 LLM 调用的真实费用之和（含查询改写，口径与 `llm_call_logs` 一致）。
- 缓存命中为 `0.0`；拒答且未调 LLM 为 `0.0`。
- 字段只增不改；前端可忽略。`QaDoneData.cost_yuan` 默认 0.0，旧测试不因缺字段失败。

## 4. 数据集契约

`eval/datasets/qa_set_m2.jsonl`：

- 40 行，UTF-8 JSONL，无空行；`QACase` 仍 `extra=forbid`。
- 30 条 `should_refuse=false` 且 `gold_chunk_ids` 非空；10 条 `should_refuse=true` 且 gold 为空。
- id `q001`–`q040` 唯一；question 去空白后非空；gold 必须是当前 user 18 的真实 chunk。
- `scope` 是中文主题标签，不是 API 过滤参数；在线评测不传 scope，避免把标签误当 subject_id。
- gold 由 AI 按 chunk 内容预标注，用户抽查；文档写“AI 预标注 + 用户抽查”，不写“纯人工标注”。

### 4.1 题目清单

| id | 问题 | gold chunk | 应拒 |
|---|---|---|---:|
| q001 | 函数的定义域怎么求？ | 254 | 否 |
| q002 | 函数的三要素是什么？ | 254 | 否 |
| q003 | 单调性的定义是什么？ | 250, 256 | 否 |
| q004 | 如何判断一个函数在区间上的单调性？ | 256 | 否 |
| q005 | 复合函数“同增异减”是什么意思？ | 256 | 否 |
| q006 | 已知奇函数在 x≥0 的解析式，怎么求 x<0 的解析式？ | 258, 260, 262 | 否 |
| q007 | 求奇函数分段解析式的套路是什么？ | 262 | 否 |
| q008 | 错位相减法的适用条件是什么？ | 255 | 否 |
| q009 | 错位相减法的五个步骤是什么？ | 257 | 否 |
| q010 | 用错位相减法求 S_n=1·2+3·2^2+…+(2n-1)·2^n。 | 261, 263 | 否 |
| q011 | 错位相减法最后化简得到的 S_n 是什么？ | 263 | 否 |
| q012 | 错位相减法有哪些易错点？ | 264 | 否 |
| q013 | 错位相减法的口诀是什么？ | 265 | 否 |
| q014 | 试卷第 1 题：下列对应关系中能构成函数的是？ | 268, 254 | 否 |
| q015 | 试卷第 2 题：f(x)=√(3-x)+ln(x+1) 的定义域是什么？ | 269, 254 | 否 |
| q016 | 试卷第 3 题：下列函数在 (0,+∞) 上单调递增的是？ | 270, 256 | 否 |
| q017 | 试卷第 4 题：偶函数 f(2)=3，f(-2) 等于多少？ | 271 | 否 |
| q018 | 试卷第 5 题：f(x)=x^3+x 的图象关于什么对称？ | 272 | 否 |
| q019 | 试卷第 6 题：f(x)=2x+1，f(f(x)) 等于多少？ | 273 | 否 |
| q020 | 试卷第 7 题：f(x)=x^2-2x+3 在 [0,m] 上最大 3 最小 2，m 范围？ | 274 | 否 |
| q021 | 试卷第 8 题：奇函数在 (0,+∞) 增且 f(1)=0，f(x)>0 的解集？ | 275, 256 | 否 |
| q022 | 试卷第 9 题：分段函数 f(f(-1)) 怎么求？ | 277 | 否 |
| q023 | 试卷第 10 题：f(x)=x+4/x（x>0）的最小值？ | 278 | 否 |
| q024 | 试卷第 11 题：f(x)=(k-2)x^2+(k-1)x+3 是偶函数，k 等于？ | 279 | 否 |
| q025 | 试卷第 12 题：f(x) 增函数且 f(m-1)>f(2m)，m 范围？ | 280, 256 | 否 |
| q026 | 试卷第 13 题：求三个函数的定义域。 | 282, 254 | 否 |
| q027 | 试卷第 14 题：用定义证明 f(x)=x+1/x 在 (1,+∞) 上单调递增。 | 283, 256 | 否 |
| q028 | 试卷第 15 题：奇函数在 (-2,2) 减，f(1-a)+f(1-2a)>0，求 a。 | 284, 256 | 否 |
| q029 | 试卷第 16 题：二次函数过 (0,3)，对称轴 x=1，f(-1)=0，求解析式及 [-2,2] 最值。 | 285 | 否 |
| q030 | 试卷第 17 题：商品进价 40，售价 50 卖 500，每涨 1 元少 10 件，求利润函数和最大利润。 | 286 | 否 |
| q031 | 今天北京天气怎么样？ | — | 是 |
| q032 | 怎么用 Python 写一个网页爬虫？ | — | 是 |
| q033 | 《红楼梦》的作者是谁？ | — | 是 |
| q034 | 出国留学需要准备哪些材料？ | — | 是 |
| q035 | 今天股市行情怎么样？ | — | 是 |
| q036 | 如何做番茄炒蛋？ | — | 是 |
| q037 | 世界杯冠军是谁？ | — | 是 |
| q038 | 电脑蓝屏怎么修？ | — | 是 |
| q039 | 怎样提高英语听力？ | — | 是 |
| q040 | 汽车轮胎多久换一次？ | — | 是 |

## 5. 在线评测行为

### 5.1 CLI

```bash
.venv/Scripts/python.exe eval/run.py \
  --dataset qa_set_m2 --config all \
  --api-base-url http://127.0.0.1:8000 \
  --token <jwt> \
  --min-items 40 --max-items 40
```

也支持：

```bash
--username test1 --password <password>
EVAL_TOKEN=<jwt>
EVAL_PASSWORD=<password>  # 与 --username 或 EVAL_USERNAME 配合
```

- 鉴权优先级：`--token` > `EVAL_TOKEN` > 用户名密码。
- 凭据不写入结果、不打印；错误信息只报“登录失败/401”，不回显 token/密码。
- `--user-id` 只在脚本模式使用；在线模式忽略，身份以 token 为准。
- 单个配置也可跑：`--config vector|hybrid|hybrid_rerank`。

### 5.2 HTTP 调用

- 登录：`POST /api/v1/auth/login`，取 `data.access_token`；401/网络失败退出 5。
- 检索：`POST /api/v1/retrieval/search`，body：
  ```json
  {"query": "...", "top_k": 5, "retrieval": "vector"}
  ```
  不传 scope；按返回 `hits[].chunk_id` 顺序算 hit@5/MRR@5。
- 回答：`POST /api/v1/qa/ask`，body `{"question": "..."}`；每个 case 新会话，SSE 解析：
  - `meta` 取 citations（chunk_id/title/heading/snippet）；
  - `delta` 累积答案文本；
  - `done` 取 refused/refusal_reason/tokens/latency_ms/cost_yuan/conversation_id；
  - `error` 立即失败，不把半截答案当结果。
- 回答结束后 `DELETE /api/v1/qa/conversations/{id}` 清理；删除失败只警告，不影响指标。
- 超时：连接 10s，单请求读取 180s；SSE 总时长不得超过 180s。
- 在线模式不调用 `new_session`、`retrieve_*`、`answer_question`；测试用 monkeypatch 保证这条边界。

### 5.3 配置执行

`--config all` 固定顺序：

1. `vector`：只检索；
2. `hybrid`：只检索；
3. `hybrid_rerank`：检索 + 回答（除非 `--skip-answer`）。

回答只跑生产配置（已确认）。vector/hybrid 不调 LLM，不产生回答指标。

### 5.4 输出

每个配置：

- `eval/results/s3-9-{config}.json`：逐题检索/回答明细、配置、模式、base_url、时间；
- `eval/results/s3-9-{config}.md`：单配置摘要。

`all` 模式额外：

- `eval/results/s3-9-compare.md`：三配置横向表。

单配置可用 `--output` / `--md-output` 覆盖路径；`all` 模式使用固定文件名，避免覆盖 S1 结果。

## 6. 指标与人工核对

### 6.1 自动指标

- 检索（30 条应答题）：`hit@5`、`MRR@5`、平均检索延迟。
- 回答（仅 `hybrid_rerank`）：
  - 引用精确率 = `|引用 chunk ∩ gold| / |引用 chunk|`；
  - 引用命中率 = 至少引用一个 gold 的应答题比例；
  - 拒答准确率 = `(TP+TN)/40`，混淆矩阵按“应拒/实际拒”；
  - 平均 tokens、平均回答延迟、总费用（`cost_yuan` 求和）。
- 被拒答的应答题引用精确率记 0、命中记 false；应拒题不参与引用指标。
- 向量配置延迟是“混合检索中的向量部分”，不是独立 SQL 基准；与 S1-7 同口径。

### 6.2 逐条核对

`docs/EVAL_M2.md` 必须包含 40 行表：

| 字段 | 说明 |
|---|---|
| id / question | 题号与问题摘要 |
| should_refuse | 数据集标注 |
| actual_refused | API 实际拒答 |
| gold_chunk_ids | 标注 gold |
| cited_chunk_ids | API 实际引用 |
| citation_ok | 引用是否真的支持答案（不只是“命中 gold”） |
| refusal_ok | 实际拒答/作答是否合适（检查数据集标注本身） |
| note | 不对/可疑的原因 |

- 由我逐条阅读真实输出后填写；用户抽查争议题。文档写“逐条核对（AI 初核 + 用户抽查）”，不冒充独立人工标注。
- `citation_ok` 与 `refusal_ok` 不参与自动指标，单独统计“核对通过数/40”。
- 失败题必须解释，不允许只写“模型问题”。

## 7. 测试策略

### 7.1 后端

- schema：接受三种 `retrieval`；未知值 422；`vector/hybrid + rerank=true` 与 `hybrid_rerank + rerank=false` 422；缺省保持原行为。
- service：
  - vector 返回 `result.vector[:top_k]`，不调用 rerank；
  - hybrid 返回 `result.fused`，不调用 rerank；
  - hybrid_rerank 调用 rerank，返回 reranked；
  - 缺省 `rerank=false` 仍走 fused；缺省配置 true 仍走 rerank。
- API：三种 body 均 200，响应 `rerank` 正确；冲突 422/42200。
- QA：`done.cost_yuan` 等于 LLM 费用之和；缓存/纯拒答为 0。
- 全量 pytest 不回归。

### 7.2 评测脚本

- 数据集：40 条通过；39/41 条报错；重复 id、应拒有 gold、应答无 gold 报错。
- SSE 解析：meta→delta→done；多字节 UTF-8；error；缺 done；未知事件忽略。
- HTTP：Authorization header、登录 body、检索 body 三模式、回答新会话、清理 DELETE。
- 在线边界：monkeypatch `new_session` 为抛错，在线模式仍能完成 fake HTTP 注入。
- 输出：三配置表行数/列名；token/密码不出现在 JSON/Markdown/异常文本。
- 退出码：2 数据/配置、4 外部、5 API/鉴权；在线模式不出现 3。

### 7.3 前端

S3-9 不改前端；若 `QaDoneData` 类型同步加 `costYuan`，跑现有 114 条测试即可，不新增页面。

## 8. 验收

1. 40 条 M2 数据集通过校验，gold 全部在当前 250–286 中。
2. 真实服务 + 真实 DashScope，`--config all` 跑完三配置；vector/hybrid 不调 LLM，hybrid_rerank 完成 40 条问答。
3. `s3-9-compare.md` 有三行真实数字；`docs/EVAL_M2.md` 有 40 行核对表。
4. 真实数字记录：hit@5、MRR@5、引用精确率/命中率、拒答准确率与混淆矩阵、平均 tokens、平均延迟、总费用。
5. 后端全量 pytest 通过；前端 114 条通过（若未改前端则记录未运行原因）。
6. 无 token/密码写入仓库、日志、结果。
7. 文档同步：API.md、PROGRESS、DECISIONS（D-043）、AI 实施计划、spec/plan 实施记录。

## 9. 风险与已知限制

- 数据集只有 40 条、语料 37 块，统计意义有限，不能外推为生产 SLA。
- gold 是 AI 预标注 + 用户抽查，存在选择偏差；`hit@5` 只能说明“当前流程命中这版 gold”。
- `citation_ok` / `refusal_ok` 是主观逐条判断，不是独立双人标注。
- vector 延迟复用混合检索调用，偏保守；不是严格隔离的纯向量基准。
- 回答只跑生产配置，vector/hybrid 没有回答质量数字。
- 在线评测依赖本机服务、真实 Key 和网络；CI 不能完整复现。
- 会话清理 best-effort，失败可能留下无引用会话。
- `cost_yuan` 以 LLM 返回 usage 为准；失败调用无 usage 时记 0，费用可能偏低。
- 40 条真实回答可能耗时数分钟、产生真实费用；执行前确认服务与额度。

## 10. 文档与决策

- `docs/EVAL_M2.md`：方法、三配置表、40 行核对、失败解释、局限。
- `docs/DECISIONS.md` D-043：API `retrieval` 模式、`cost_yuan`、在线评测边界、数据重建、人工核对口径。
- `docs/API.md`：`retrieval` 字段、冲突规则、`done.cost_yuan`。
- `docs/PROGRESS.md`：S3-9 状态、真实数字、已知限制。
- `docs/AI协作开发实施计划.md`：S3-9 勾选 + 实施记录。
- `docs/plan/s3-9-online-eval.md`：分步实现与验证命令。

## 11. 实施记录（2026-11-02）

- 按本 spec 完成；plan 的 8 个任务全部落地，未新增依赖/迁移/前端页面。
- 真实跑数发现并修正两个口径问题：① 在线客户端初版把 `meta` 全上下文当引用，精确率 0.228；改为正文 `[n]` 后 0.897；② 首次重跑命中 S3-7 QA 缓存（tokens=0/费用=0），清空 `qa:v1:*` 后重跑。
- 最终真实数字：vector **1.000/0.957/14ms**，hybrid **1.000/0.790/15ms**，hybrid_rerank **1.000/0.978/14ms**（hit@5/MRR@5/检索延迟）；生产回答引用精确率 **0.897**、命中率 **1.000**、拒答准确率 **82.5%**、平均 tokens **1929.7**、平均回答延迟 **12901ms**、总费用 **¥0.088384**。
- 自动拒答 82.5% 与人工 10/10 的差异：7 条 off-topic 走 chitchat，回复内容上拒绝但不置 `refused`；已在 `docs/EVAL_M2.md` 解释，不粉饰。
- 测试：后端 **770 passed, 1 warning**；前端未改，沿用 S3-8 的 114/29。用户已抽查 q001/q010/q014/q021/q028 通过。