# S5-4 在线作答与判分 → 掌握度回写（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S5-4。产出 `answers` 表、作答接口、`views/papers/Take.vue`。
> 状态：**待用户确认**（2026-11-13）。确认后才写 plan。

## 1. 目标与非目标

### 1.1 目标
1. 学生能把已保存的试卷当成一次练习来做：看到题干/选项，作答，随时中断，回来接着答。
2. 单选/多选**自动判分**；填空/解答学生**自评 对=1 / 半对=0.5 / 错=0**。
3. 交卷一次请求：写 `answers`、按知识点回写 `mastery`（复用 S4-7 公式）、把非满分且有作答的题写入错题本、把试卷置 `已提交`。
4. 交卷响应给出每题判定 + 每个知识点的掌握度 before/after，页面直接展示「导数 0.42 → 0.51」。
5. 已提交试卷只读回看，重复交卷/再自动保存 409。
6. 自动化测试（后端服务 + 接口、前端 API + 页面）与真机验收（真实学生/真实卷）。

### 1.2 非目标（留给后续卡）
- 不做「重新作答/重置已交卷」，避免掌握度重复累计（S5-7 练习中心再议）。
- 不做草稿列表/删除（PROGRESS 待解决问题 100）。
- 不做交卷即自动错因诊断（用户确认：控 LLM 成本，错题本里手动点）。
- 不做整卷计时服务端校验（`duration_min` 只做展示/参考，超时不强制收卷）。
- 不做非试卷练习的 `paper_id=NULL` 作答入口（表结构支持，接口本轮只挂试卷）。

## 2. 用户已确认的决策（2026-11-13）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 接口形态 | **试卷作用域 3 接口**：`GET /papers/{id}/answers`、`PUT /papers/{id}/answers/{question_id}`、`POST /papers/{id}/submit`；权限/试卷状态只校验一处 |
| D2 | 解答题自评时机 | **交卷前必须全部自评**：前端禁用交卷并提示，后端再拦 409 |
| D3 | 错题入库口径 | **非满分且有作答**（`score < item.score` 且 `user_answer_md` 去空白非空）；空白未答只扣掌握度，不算错题 |
| D4 | 错因诊断 | **不自动触发**；交卷只入库，错题本里手动「诊断」 |
| D5 | 掌握度反馈 | 响应内给 `{kp_id, kp_name, mastery_before, mastery_after, attempts_delta}`；**不落库快照** |
| D6 | 重复提交 | **只读回看 + 409 拦截**；GET 可看结果，PUT/交卷 409「试卷已提交」 |
| D7 | 填空题判分 | **填空也让学生自评**（对/半对/错）——**偏离任务卡「客观题自动判分」的字面口径**，用户明确选择；单选/多选仍自动判分 |
| D8 | 作答页形态 | **单页 + 题号面板 + 自动保存**；顶部计时/进度，交卷确认后显示成绩与掌握度变化 |

> D7 的连带影响：自评必填题 = `填空` + `解答`；只有 `单选/多选` 自动判定。`self_rated` 对填空/解答写 0/0.5/1，对单选/多选写 1.0（满分）或 0.0。

## 3. 数据模型：`answers`（迁移 `0015_s5_4`）

按 SCHEMA §6.2 落表，并补三处实现口径（同步写回 SCHEMA）：

| 字段 | 类型 | 可空 | 约束/默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT | 否 | Identity PK | |
| user_id | BIGINT | 否 | FK `users.id` ON DELETE CASCADE | 作答者 |
| question_id | BIGINT | 否 | FK `questions.id` ON DELETE RESTRICT | 题目 |
| paper_id | BIGINT | 是 | FK `papers.id` ON DELETE CASCADE | 非试卷练习为 NULL（本轮只写非 NULL） |
| user_answer_md | TEXT | 是 | | 作答内容；选择题存规范化前的原文（如 `AC`），前端展示原样 |
| is_correct | BOOLEAN | 是 | | 草稿为 NULL；交卷后必填 |
| score | NUMERIC(6,2) | 是 | `score >= 0` | 半对可能是 2.50，故用 NUMERIC；**SCHEMA 原写 NUMERIC 未定精度，本轮定为 (6,2)** |
| self_rated | NUMERIC(2,1) | 是 | `self_rated IN (0, 0.5, 1)` | 填空/解答自评；单选/多选交卷后写 1.0 或 0.0 |
| time_spent_sec | INTEGER | 是 | `time_spent_sec >= 0` | 该题累计用时（秒） |
| created_at | TIMESTAMPTZ | 否 | `now()` | 首次保存时间；自动保存只更新内容不改它 |

索引：
- `ix_answers_user_question (user_id, question_id)`：SCHEMA 要求的按人按题查。
- `ix_answers_paper_id (paper_id)`：续答按卷取行。
- **`uq_answers_user_paper_question (user_id, paper_id, question_id) WHERE paper_id IS NOT NULL`**（部分唯一）：自动保存是 upsert，一个人在一张卷里对一题只有一行；NULL（非试卷练习）不参与唯一，留给后续卡。

> 为什么不加 `updated_at`：SCHEMA 没有该列，本轮不扩；「最后保存时间」由 `created_at` + 前端本次会话状态表达，不引入新列。

## 4. 判分规则（纯函数，`services/answer_service.py`）

### 4.1 客观题：单选 / 多选
- 归一化 `normalize_choice(text)`：全角字母转半角、转大写、提取 `A-H` 字母集合、排序；`A,C`、`a c`、`CA` 都等价于 `{A,C}`。
- `单选`：用户集合 == 答案集合，且答案集合大小为 1；否则错。
- `多选`：用户集合 == 答案集合（顺序无关、多选少选都错）；否则错。
- 答案来源：`questions.answer_md`。

### 4.2 自评题：填空 / 解答
- 必须给 `self_rated ∈ {0, 0.5, 1}`；缺失 → 409（D2）。
- `score = item.score × self_rated`（`Decimal` 运算，落库定型 2 位）。
- `is_correct = (self_rated == 1)`。

### 4.3 汇总
- `score_total = Σ item.score`（客观按对错、自评按比例）。
- 每题输出 `{question_id, qtype, is_correct, score, self_rated, user_answer_md}`。
- 未作答：`user_answer_md=None`，客观判错、自评题必须有 self_rated（前端必须让用户点一个；点「错」即 0）。

## 5. 掌握度回写（复用 S4-7）

对每题：
1. `s`：客观题 `1.0/0.0`；自评题 `self_rated`（0/0.5/1）。
2. `difficulty = questions.difficulty`。
3. `kp_ids = question_kps.kp_ids`（一题可能挂多个知识点；一次作答同时更新多个）。
4. 调用 `mastery_service.record_attempts(session, user_id=..., kp_ids=..., s=..., difficulty=..., now=now)`；它内部懒创建、flush，**不 commit**。

交卷结束时统一 commit；同卷多题命中同一 kp 时按卷面顺序连续更新（`record_attempts` 每次读已 flush 的行，结果等价于逐次作答）。

响应 `mastery` 列表：每个被触碰的 kp 取「本卷第一次触碰前」的 mastery 与「最后一次后」的 mastery，`attempts_delta` 为本卷触碰次数；`kp_name` 一次 `IN` 批量查 `knowledge_points.name`，查不到留空字符串（知识点被硬删的极端情况不 500）。**之前没有 mastery 行的 kp，`mastery_before=null`**（SCHEMA：无行=未评估，不是 0 掌握），前端显示「未评估 → 0.08」。

## 6. 错题自动入库（复用 S4-2 语义，不 commit）

- 触发：`score < item.score` **且** `user_answer_md` 去空白非空（D3）。
- 写入：新增 `mistake_service.record_wrong_answer(session, *, user_id, question_id, my_answer_md, correct_answer_md)`：
  - 查询 `(user_id, question_id)` 既有错题；
  - 有 → 复用 `_reset_reentry`（状态回 `待订正`、连对清零、覆盖本次作答）；
  - 无 → 新增 `Mistake(status="待订正", correct_streak=0)`；
  - 只 `flush`，**不 commit**；不触发诊断入队（D4）。
- 交卷事务里逐题调用，最终与 `answers`/`mastery`/试卷状态一起提交；中途异常整体回滚，不出现「答了但掌握度没动」。
- 响应 `mistake_question_ids`：本卷实际写入/重置的题号（升序、去重）。

## 7. 接口（先改 `docs/API.md §8`，再写代码）

### 7.1 `GET /api/v1/papers/{id}/answers`
- 权限：student，本人。
- 出参 `Envelope[PaperAnswersOut]`：
  ```json
  {
    "paper": {"id": 8, "title": "验收卷", "status": "草稿", "total_score": 44},
    "items": [
      {"question_id": 501, "user_answer_md": "A", "self_rated": null,
       "is_correct": null, "score": null, "time_spent_sec": 32, "saved": true}
    ],
    "submitted": false,
    "earned_score": null
  }
  ```
- `items` 按 `papers.question_ids` 顺序；没有作答记录也返回占位行（`saved=false`）。缺题（被硬删）跳过，不 500（与 `GET /papers/{id}` 口径一致）。
- `submitted=true` 时 `earned_score` = 各行 score 之和。

### 7.2 `PUT /api/v1/papers/{id}/answers/{question_id}`
- 权限：student，本人；入参：
  ```json
  {"user_answer_md": "AC", "time_spent_sec": 48}
  ```
  `user_answer_md` 可空（清除），长度 ≤ 20000；`time_spent_sec` 0–86400 可空。
- 行为：只在 `草稿/已生成` 卷上允许；upsert 一行，不判分（`is_correct/score/self_rated` 保持 NULL）。
- 出参：`Envelope[PaperAnswerOut]`（同上单行）。
- 错误：试卷不存在 404/40400、别人的 403/40300、已提交 409/40900、题目不在卷内 422/42200。

### 7.3 `POST /api/v1/papers/{id}/submit`
- 权限：student，本人；入参：
  ```json
  {"items": [{"question_id": 501, "user_answer_md": "A", "self_rated": null, "time_spent_sec": 32}]}
  ```
  - `items` 必须覆盖卷内每道现存题目一次（可整卷传 `user_answer_md=null` 表示未答）；重复题号 422；卷外题号 422。
  - `self_rated` 只允许空/0/0.5/1；填空/解答必须给；单选/多选给了也忽略（按自动判定）。
- 行为（**单事务**）：校验 → 判分 → upsert 所有 `answers` 行 → `record_attempts` 逐题 → 错题入库 → `papers.status='已提交'` → 一次 commit。
- 出参 `Envelope[PaperSubmitOut]`：
  ```json
  {
    "paper_id": 8, "score": 31, "total_score": 44,
    "correct_count": 5, "question_count": 12, "elapsed_sec": 1234,
    "items": [{"question_id": 501, "qtype": "单选", "is_correct": true,
               "score": 3, "self_rated": 1.0, "user_answer_md": "A"}],
    "mastery": [{"kp_id": 117, "kp_name": "函数的单调性",
                 "mastery_before": 0.42, "mastery_after": 0.51, "attempts_delta": 2},
                {"kp_id": 120, "kp_name": "导数的几何意义",
                 "mastery_before": null, "mastery_after": 0.08, "attempts_delta": 1}],
    "mistake_question_ids": [502, 505],
    "missing_question_ids": []
  }
  ```
- 错误：不是本人 403、不存在 404、已提交 409（D6）、填空/解答未自评 409（消息「还有 N 道题未自评」）、`self_rated` 非法 422、题号重复/卷外 422。

### 7.4 错误码复用
`ConflictError` 409/40900、`InvalidParamError` 422/42200、`NotFoundError` 404/40400、`AuthError` 401/40100、`PermissionDenied` 403/40300；不新增错误类型。

## 8. 前端

### 8.1 路由与入口
- 新路由 `/papers/:id/take`，`meta {title: '在线作答', nav: 'papers', roles: ['student']}`。
- `Generate.vue` 保存成功后除两个导出按钮外新增「开始作答」→ `router.push(\`/papers/${id}/take\`)`。
- 直达 URL 可打开（从组卷页复制）。

### 8.2 `Take.vue` 单页
- 加载：`getPaper(id)`（题干/答案/解析）+ `getPaperAnswers(id)`（续答）。
- 布局：
  - 顶部：标题、状态、总分、已答/总题数进度、计时（`已用时 mm:ss`）。
  - 左侧/主区：当前题卡片（题型/分值/难度、`MathText` 题干、选项或输入框、填空/解答旁自评 radio「对 / 半对 / 错」）。
  - 右侧题号面板：每题按钮，状态色 未答/已答/当前；点击跳题。
  - 底部：上一题/下一题/交卷。
- 自动保存：作答变化或切题前 debounce 800ms 调 `PUT`，请求带上该题累计秒数；显示「已保存 HH:mm:ss」；失败保留本地并提示（http.ts 已统一弹错）。
- 计时：`setInterval` 只累加**当前题**秒数；切题把累计值随保存提交；续答时以服务端返回的 `time_spent_sec` 为基数继续累加；整卷已用时 = 各题累计 + 当前题实时。
- 交卷：确认框列出未答数；填空/解答未自评则前端拦住并提示「还有 N 道题未自评」（不发请求）；成功后展示成绩面板：得分/总分、正确题数、错题已入库数、每个 kp 的「before → after」与 ↑/↓ 标识；按钮「查看错题本」「返回组卷」。
- 已提交：只读模式，题卡显示学生答案、正确答案、得分与解析，禁止编辑；顶部显示成绩。

### 8.3 类型与 API
`web/src/types/papers.ts` 追加 `PaperAnswerRow`、`PaperAnswers`、`PaperAnswerPayload`、`PaperSubmitPayload/Result`、`MasteryDelta`；`web/src/api/papers.ts` 追加 `getPaperAnswers`、`savePaperAnswer`、`submitPaper`。

## 9. 事务、幂等与并发

- 自动保存：`SELECT ... FOR UPDATE` 不必要；依赖部分唯一索引 + `INSERT ... ON CONFLICT DO UPDATE`（SQLAlchemy `postgresql.insert(...).on_conflict_do_update`）保证并发同一题只一行。
- 交卷：先 `session.get(Paper, id)` 并校验状态；并发双交卷时后到者可能读到 `草稿`，在最终 `UPDATE papers SET status=已提交` 用条件更新（`WHERE id=... AND status IN ('草稿','已生成')`）判 `rowcount=0` → 回滚并 409，避免双写掌握度。
- 掌握度/错题与试卷状态同一 commit；异常统一 rollback 并抛 AppError。
- 交卷幂等性不做「重复提交返回上次结果」（D6 选择 409）。

## 10. 测试计划（TDD，先红后绿）

### 10.1 后端服务 `tests/test_answer_service.py`（约 14 条）
1. `normalize_choice` 全角/小写/分隔符/顺序。
2. 单选对/错/多字母。
3. 多选全对/少选/多选/乱序。
4. `score_total` 客观 + 自评 0.5 的半对分数（如 8 分题 → 4.00）。
5. 自评缺失抛 `ConflictError`（消息含剩余数量）。
6. `self_rated=0.7` 抛 `InvalidParamError`。
7. 卷外 question_id / 重复 question_id → `InvalidParamError`。
8. `submit_answers` 编排（FakeSession）：答案 upsert、`record_attempts` 每题一次且 s 正确、错题只收「非满分且有作答」、paper.status 变已提交、commit 一次。
9. 已提交卷 → `ConflictError`。
10. 空白未答不计错题但 mastery 仍更新（s=0）。
11. 题型判定：单选/多选忽略传入 self_rated。
12. mastery 聚合 before/after 与 attempts_delta。
13. 缺题跳过并进 `missing_question_ids`。
14. 客观题答案大小写/全角差异仍判对。

### 10.2 后端接口 `tests/test_answers_api.py`（约 10 条）
1. 未登录 401；别人的卷 403；不存在 404。
2. GET 续答：按卷面顺序 + 未答占位 + submitted/earned_score。
3. PUT 自动保存 200 并 upsert（连续两次只一行）。
4. PUT 已提交 409；题目不在卷 422；`time_spent_sec=-1` 422。
5. POST 交卷 200：score/correct_count/items/mastery/mistake_question_ids 正确。
6. POST 未自评 409（消息含数量）。
7. POST 重复交卷 409。
8. POST `self_rated=0.7` 422。
9. POST 题号重复/卷外 422。
10. 响应不泄露内部异常文本。

> 测试全部 fake session（照 S4/S5 既有风格），不连真库、不跑真实 mastery 公式以外的外部调用；`record_attempts` 用真实纯函数 + fake session 行，或用 monkeypatch 捕获参数（plan 里定）。

### 10.3 前端
- `api/papers.spec.ts` +3：三个函数路径/载荷。
- `views/papers/Take.spec.ts` +6：首题渲染（题干/选项）、选择触发自动保存、未自评拦住交卷、交卷成功展示成绩与掌握度变化、续答回填已存答案、已提交只读。
- `Generate.spec.ts` +1：保存后「开始作答」跳转 `/papers/{id}/take`。

### 10.4 迁移
- 本地 `alembic upgrade head` 后 `\d answers` 核对列/CHECK/部分唯一索引；`alembic downgrade -1` 可回退。

## 11. 真机验收（`E:\BiShe-AIStudy\.sdd\s5-4\`）

1. 起后端 8000 + 前端 5173（沿用 S5-3 环境）。
2. 用学生 50 生成并保存一张**实际可组出的最大卷**（任务卡写 20 题，真实库 S5-2 实测仅 19 道可用；以实际 `ok/题数` 为准，**如实记录缺口**）。
3. 脚本/浏览器作答：单选多选按「对/错」混合；填空解答逐题自评（对/半对/错混搭）；交卷。
4. 核对：
   - `answers` 行数 = 卷内题数，`is_correct/score/self_rated` 符合判分表；
   - `papers.status='已提交'`；
   - `mastery` 对应 kp 的 mastery/attempts/stability/due_at 变化方向符合公式（至少 1 个 kp 手算对照：M' = M + K_eff·(s−M)，K_eff=0.35/difficulty）；
   - 错题本新增/重置行数 = 非满分且有作答的题数，`status='待订正'`；
   - 重复交卷 409、续答 GET 回填、刷新后答案不丢；
   - 前端展示的 before→after 与库内一致。
5. 证据落 `.sdd/s5-4/acceptance-evidence.md`（命令、原始数字、截图），PROGRESS 只写实测数字。

## 12. 风险与边界（写进 PROGRESS/DECISIONS）

1. **填空自评**（D7）与任务卡「客观题自动判分」字面不一致，是用户明确选择；好处是不误判 LaTeX/多空填空，代价是学生可虚报。
2. 半对会产生小数分 → `score NUMERIC(6,2)`，与「分数用整数」的既有约定有例外，写入 DECISIONS。
3. 已提交不可重做：学生误交只能找老师/后续卡处理。
4. 自动保存失败（网络断）只保前端内存，刷新会丢最后一次未保存改动；接受。
5. 试卷题被硬删：续答/交卷跳过并进 `missing_question_ids`，总分按现存题计。
6. 无草稿列表：学生只能从组卷页或 URL 进入；已在 PROGRESS 问题 100 记录。
7. 错题本条目会复用重置（S4-2 D-1）：同一题历史作答被覆盖，无历史时间线。

## 13. 文档同步
- `docs/API.md §8`：替换 `POST /answers` TODO 为 3 个接口的完整契约（含错误码/示例）。
- `docs/SCHEMA.md §6.2`：补 `score NUMERIC(6,2)`、`self_rated` CHECK、部分唯一索引、FK；§6.1 papers 状态说明补「交卷置已提交」。
- `docs/DECISIONS.md`：D-061（3 接口、交卷单事务、自评口径、错题口径、不自动诊断、小数分例外）。
- `docs/PROGRESS.md`：S5-4 完成行、关键口径、验收数字、待解决问题（若发现）。
- `AGENTS.md §9.2/§9.6`：作答/判分锚点。
- `.env.example`：无新增环境变量。
- 勾选实施计划 S5-4。