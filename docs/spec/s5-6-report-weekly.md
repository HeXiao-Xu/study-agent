# S5-6 学习报告（雷达 / 热力 / 趋势 + 周报）（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S5-6。产出 `services/report_service.py`、`api/v1/reports.py`、`prompts/weekly_report_v1.md`。
> 状态：**已确认**（2026-11-14）。按本 spec 写 `docs/plan/s5-6-report-weekly.md`。
> 范围：只做后端报告聚合与周报生成；`views/reports/Index.vue`、范围切换、导出图片归 S5-7。

## 1. 目标与非目标

### 1.1 目标

1. `GET /api/v1/reports/mastery` 一次返回学习报告三块数据：模块雷达、知识点 Treemap、近 N 天趋势。
2. 雷达按 level=2 模块聚合**当前**有效掌握度 `M_t`；未评估的模块返回 `null`，不把「没学过」画成 0。
3. 热力图覆盖 level 2–4 全部知识点，颜色值为 `1 − M_t`；未评估节点为 `null`，前端画灰块。
4. 趋势按 UTC 日界补零，返回新增笔记、完成复习、新增错题、已掌握错题及净增五列。
5. `POST /api/v1/reports/weekly` 用最近 7 天结构化统计生成 Markdown 周报；只允许使用输入中出现的数字。
6. 周报生成走数字校验：提取报告中的阿拉伯数字，逐个与输入统计比对；不通过则带非法数字重试，最多 2 次；仍失败返回 500/50000，不返回不可追溯报告。
7. 新增 `llm_call_logs.scene='report'`，让周报调用能单独出现在用量统计里；加迁移 `0017_s5_6`。
8. 自动化测试覆盖纯函数、service、LLM 适配器、API、迁移；真机用真实学生数据验证 GET 与真实 LLM 周报。

### 1.2 非目标（留给后续卡）

- 不做 `/reports` 前端页、ECharts 配置、时间范围切换控件、导出图片（S5-7）。
- 不做家长/老师查看学生报告；本卡只允许 student 查本人（与 S4-8 一致）。
- 不新增报告表、不保存历史周报；`POST /reports/weekly` 每次现场生成。
- 不补 S5-5 的复习历史事件；`reviews_done` 只能基于当前 `review_items.done_at` 快照。
- 不生成「复习完成率」与「薄弱点变化」这两个缺少历史数据支撑的指标。
- 不做思维导图（Mermaid）与 PDF/图片导出。
- 不改 S4-8 `/stats/overview`；报告是独立接口。

## 2. 用户已确认的决策（2026-11-14）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 接口面 | `GET /reports/mastery` + `POST /reports/weekly`；周报单独 POST，不隐式写库 |
| D2 | 时间范围 | `range=7d|30d|90d`，默认 `30d`；雷达/热力为当前快照，范围只影响趋势 |
| D3 | 雷达聚合 | level=2 模块内**已评估**知识点 `M_t` 简单均值；无评估行返回 `null` |
| D4 | 热力图范围 | 全部 level 2–4 节点；未评估 `mastery/mastery_t/color_value=null` |
| D5 | 趋势指标 | 每日 `new_notes`、`reviews_done`、`new_mistakes`、`mastered_mistakes`，并给 `mistakes_net` |
| D6 | 周报方式 | 同步 `POST`，滚动最近 7 天，不落库 |
| D7 | 周报指标边界 | 只用现有可算指标，不编造复习完成率/薄弱点变化，文档明确限制 |
| D8 | 数字校验失败 | 重试 2 次仍失败则 500/50000，不返回报告 |
| D9 | 学科维度 | 按 `subjects` 分组返回；不提供 `subject_id` 过滤（S5-7 按需取第一个） |
| D10 | 日界 | UTC，与 S4-8 `/stats/overview` 一致 |
| D11 | LLM scene | 新增 `report` 场景 + 迁移 `0017_s5_6` 扩展 CHECK |

## 3. 数据口径与纯函数

### 3.1 窗口与补零

- `build_window(range_key, now)`：与 `stats_service.build_window` 同口径。
  - 支持 `7d` / `30d` / `90d`；其他值抛 `InvalidParamError`（422/42200）。
  - 窗口 = `[今天-(N-1) 天 00:00 UTC, now]`；`dates` 升序、长度 N。
- `fill_days(rows, dates)`：缺的天补 0，折线不断。
- 所有「今天」按 UTC 计算；报告不读 `REVIEW_TIMEZONE`。

### 3.2 模块雷达

- 数据源：`knowledge_points` 全部节点 + `mastery`（本人）。
- 模块 = `level=2` 的知识点；一个模块的子树包含模块自身及全部后代（level 3/4）。
- 对子树内**有 mastery 行**的节点，逐个用 S4-7 `decayed_mastery(mastery, stability, days)` 算 `M_t`（`days = now - last_practice_at`，未来/空按 0）。
- `assessed_count` = 子树内有 mastery 行的节点数；`kp_count` = 子树节点总数（含模块自身）。
- `mastery` = 这些 `M_t` 的算术平均，保留 3 位；`assessed_count=0` 时 `mastery=null`。
- 模块按 `kp_id ASC` 返回，固定轴顺序，避免雷达图每次刷新换位置。
- `exam_weight` 原样返回 `float|null`；不参与均值。

### 3.3 知识点热力图

- 数据源：`knowledge_points` 的 level 2/3/4 节点（level 1 不返回，`subjects` 已表达学科根）。
- 扁平返回，每节点：
  - `kp_id`、`kp_name`、`level`、`exam_weight`；
  - `parent_id`：level 2 归一为 `null`；level 3/4 用真实父 id（父节点必在同一列表）；
  - `mastery`：库存原值 `float|null`；
  - `mastery_t`：折算值 `float|null`（无行 = null，不冒充 0）；
  - `color_value`：`round(1 - mastery_t, 3)`；无行 = null；
  - `assessed`：是否有 mastery 行。
- 排序：先 `level ASC`，同 level 按 `kp_id ASC`；前端可据此稳定建树。
- Treemap 的块大小由前端用 `exam_weight`（缺失时回退 1）；接口不生成面积。

### 3.4 趋势

- 窗口按 UTC 日界；每个点：

  | 字段 | 口径 |
  |---|---|
  | `date` | UTC 日期 |
  | `new_notes` | `notes.created_at` 落在当天，且 `deleted_at IS NULL`；软删笔记不回补 |
  | `reviews_done` | `review_items.done_at` 落在当天；done 与 skip 都算（库内不可区分） |
  | `new_mistakes` | `mistakes.created_at` 落在当天 |
  | `mastered_mistakes` | 当前 `status='已掌握'` 且 `mistakes.last_review_at` 落在当天 |
  | `mistakes_net` | `new_mistakes - mastered_mistakes` |

- 所有天补 0；`mastered_mistakes` 是**按当前状态回算**，不是完整状态变更历史（与 S4-8 同款限制）。
- `reviews_done` 只反映当前 `review_items` 行；某项重开后 `done_at` 被清空，历史完成数会丢失。此限制必须在 API/文档/周报 Prompt 中如实说明。

### 3.5 周报统计输入

`build_weekly_stats(session, user_id, now)`：

- `period` = 最近 7 个 UTC 日（`from=today-6`，`to=today`，`days=7`）。
- `trend` = 3.4 的 7 天结果。
- `totals` = 对 7 天逐项求和：
  `{new_notes, reviews_done, new_mistakes, mastered_mistakes, mistakes_net}`。
- `active_days` = 7 天中 `new_notes + reviews_done + new_mistakes + mastered_mistakes > 0` 的天数。
- 当前掌握度快照（`now`）：
  - `assessed_kp_count` = 本人 mastery 行数；
  - `avg_mastery` = 全部 mastery 行 `M_t` 的简单平均，保留 3 位；无行 = null；
  - `weak_modules` = 雷达中 `mastery != null` 的模块，按 `(mastery ASC, kp_id ASC)` 取前 3，字段 `{subject_id,kp_id,kp_name,mastery}`；此处的 `mastery` 是模块平均 `M_t`；
  - `weak_kps` = 热力图中 `mastery != null` 的节点（含 level 2），按 `(mastery_t ASC, kp_id ASC)` 取前 5，字段 `{subject_id,kp_id,kp_name,level,mastery}`；此处的 `mastery` 填 `M_t`（不是库存原值），与排序口径一致。
- 无学习数据判定：`totals` 五项全 0 **且** `assessed_kp_count=0`。此时 `POST /reports/weekly` 返回固定空周报，`generated_by="empty"`，不调用 LLM。

## 4. 接口契约（先改 `docs/API.md §9`，再写代码）

### 4.1 `GET /api/v1/reports/mastery`

- 权限：student（teacher/parent/admin → 403/40300）；只查本人。
- 类型：同步、只读。
- 入参：`range` 可选，`7d|30d|90d`，默认 `30d`；非法 422/42200。
- 出参：`Envelope[ReportOverviewOut]`：

```json
{
  "range": {"key": "30d", "from": "2026-10-16", "to": "2026-11-14"},
  "subjects": [
    {
      "subject_id": 7,
      "subject_name": "高中数学",
      "modules": [
        {"kp_id": 115, "kp_name": "集合与常用逻辑用语", "exam_weight": 0.8,
         "kp_count": 8, "assessed_count": 2, "mastery": 0.512}
      ],
      "heatmap": [
        {"kp_id": 115, "kp_name": "集合与常用逻辑用语", "parent_id": null,
         "level": 2, "exam_weight": 0.8, "mastery": 0.5, "mastery_t": 0.48,
         "color_value": 0.52, "assessed": true}
      ]
    }
  ],
  "trend": [
    {"date": "2026-11-14", "new_notes": 0, "reviews_done": 0,
     "new_mistakes": 3, "mastered_mistakes": 1, "mistakes_net": 2}
  ]
}
```

- `subjects` 只包含至少有一个 level=2 知识点的学科；当前库只有数学。
- `modules` 固定 level=2 全量（含无评估模块，`mastery=null`）。
- `heatmap` 固定 level 2–4 全量；`parent_id` 归一规则见 §3.3。
- `trend` 长度 = 7/30/90；按日期升序。
- 错误：401/40100、403/40300、422/42200。

### 4.2 `POST /api/v1/reports/weekly`

- 权限：student；只查本人。
- 类型：同步；可能耗时数秒（LLM），不接受客户端传入统计数字。
- 入参：无请求体。
- 出参：`Envelope[WeeklyReportOut]`：

```json
{
  "period": {"from": "2026-11-08", "to": "2026-11-14", "days": 7},
  "generated_by": "llm",
  "report_md": "## 本周概览\n...",
  "stats": {
    "totals": {"new_notes": 0, "reviews_done": 0, "new_mistakes": 3,
                "mastered_mistakes": 1, "mistakes_net": 2},
    "active_days": 1,
    "mastery": {
      "assessed_kp_count": 10,
      "avg_mastery": 0.351,
      "weak_modules": [
        {"subject_id": 7, "kp_id": 120, "kp_name": "数列", "mastery": 0.35}
      ],
      "weak_kps": [
        {"subject_id": 7, "kp_id": 197, "kp_name": "同角三角函数基本关系",
         "level": 4, "mastery": 0.144}
      ]
    },
    "trend": ["同 GET 的 7 个点"]
  },
  "validation": {
    "ok": true,
    "attempts": 1,
    "checked_numbers": ["0", "3", "1", "2", "10", "0.351", "7"],
    "invalid_numbers": []
  }
}
```

- `generated_by`：`"llm"` 或 `"empty"`。
- 空数据时：`totals` 全 0、`avg_mastery=null`、`weak_*=[]`、`attempts=0`、`checked_numbers=[]`、`report_md` 为固定文案「本周暂无学习记录，先完成一次练习或复习再来查看周报。」。
- 校验成功时 `validation.ok=true` 且 `invalid_numbers=[]`；校验失败不会返回 200 报告。
- 错误：401/40100、403/40300、500/50000「周报生成失败」（LLM 调用/数字校验重试耗尽；不泄露 Prompt、模型响应、Key）。

## 5. 周报 LLM 与数字校验

### 5.1 Prompt 与适配器

- Prompt 文件：`backend/app/ai/prompts/weekly_report_v1.md`，Jinja2 `StrictUndefined`。
- 适配器：`backend/app/ai/report/weekly_report.py`。
  - `WeeklyReportContext`：`period`、`totals`、`active_days`、`mastery`、`trend`；周报只吃这些结构化输入。
  - `render_prompt(context)` 输出完整用户消息；缺变量直接抛 `WeeklyReportError`。
  - `SCENE = "report"`；`PROMPT_VERSION = "weekly_report_v1"`。
  - 调用 `client.chat(messages, temperature=0.3, max_tokens=1400, scene=SCENE)`。
- Prompt 硬性要求：
  1. **只能使用【统计数据】中出现的数字**，不得计算、四舍五入、换算百分比或补全任何新数字；
  2. 不得使用 Markdown 有序列表（避免 `1.` 被误判为编造数字）；
  3. 输出 Markdown，四个二级标题：本周概览 / 学习投入 / 薄弱点 / 下周建议；
  4. 如果某项为 0 或空，直接写 0/「暂无」，不要推测原因；
  5. 不引用未提供的日期、排名、增长率。
- Prompt 中明确注明限制：`reviews_done` 是当前完成快照，`mastered_mistakes` 是按当前状态回算，不可写成「本周掌握了 X 个」以外的因果。

### 5.2 数字提取与校验

纯函数放在 `services/report_service.py`（不依赖 LLM）：

- `extract_numbers(text) -> list[str]`：
  - 正则提取阿拉伯数字 token（可带负号与小数），忽略 Markdown 行首 `1.` / `1)` 列表序号；
  - 保留出现顺序，重复 token 去重后返回字符串形式。
- `allowed_numbers(stats) -> set[Decimal]`：
  - 递归收集 `stats` 中所有数值叶子（bool 不算数字）；
  - 加入 `period` 年/月/日与 `days`；
  - 用 `Decimal` 归一化，`0`/`0.0`/`-0` 视为相等。
- `validate_numbers(text, stats) -> NumberValidation`：
  - 提取后逐个与 allowed 比较；返回 `{checked_numbers, invalid_numbers, ok}`；
  - 有数据（非空周报）时，报告必须至少含 1 个数字，否则 `ok=false`；
  - 只校验阿拉伯数字；中文数字（一/二/三）不纳入，Prompt 明确要求用阿拉伯数字。

### 5.3 重试与失败

- `generate_weekly_report(context, llm_client=None, max_retries=2)`：
  1. 渲染 Prompt；
  2. 调用 LLM；
  3. 校验数字；
  4. 不通过：把非法数字追加为一条 user 纠正消息（「以下数字不在输入中：…；只能使用输入中出现的数字」），再次调用；
  5. 最多 `max_retries + 1` 次；仍失败抛 `ReportGenerationError`。
- LLM 网络/鉴权异常（`LLMError`）直接包装为 `ReportGenerationError`，不再重试（底层 client 已有 2 次重试）。
- `ReportGenerationError` 是 `AppError` 子类，固定 500/50000「周报生成失败」；日志记录 attempts/非法数字，不记录完整 Prompt 与 LLM 正文。
- 空数据分支不进入 LLM，返回 `generated_by="empty"`。

## 6. 枚举与迁移 `0017_s5_6`

- `app/models/enums.py`：`LLMCallScene` 增加 `REPORT = "report"`。
- 迁移：
  - `upgrade()`：drop `ck_llm_call_logs_scene`，重建为
    `scene IN ('qa','query_rewrite','kp_align','embed','mistake','gen','graph','agent','report')`；
  - `downgrade()`：恢复不含 `report` 的旧 CHECK；
  - `down_revision = "0016_s5_5"`，`revision = "0017_s5_6"`。
- 不加表、不加列；只扩展 CHECK。
- 现有三个 head 测试（answers/papers/review）改为期待 `0017_s5_6`；新增 `tests/test_report_migration.py` 断言 head 与 CHECK。

## 7. 文件与分层

| 文件 | 内容 |
|---|---|
| `backend/app/schemas/report.py` | `ReportRangeOut`、`ReportModuleOut`、`ReportHeatmapNodeOut`、`ReportSubjectOut`、`ReportTrendPointOut`、`ReportOverviewOut`、`WeeklyPeriodOut`、`WeeklyTotalsOut`、`WeeklyMasteryOut`、`WeeklyReportOut`、`NumberValidationOut` |
| `backend/app/services/report_service.py` | 纯函数 `build_window/fill_days/aggregate_modules/build_heatmap/build_trend/extract_numbers/allowed_numbers/validate_numbers` + DB `get_overview/build_weekly_stats/generate_weekly`；不 commit |
| `backend/app/ai/report/weekly_report.py` | Prompt 渲染、LLM 调用与重试；只 import `ai.llm` 门面 |
| `backend/app/ai/prompts/weekly_report_v1.md` | 周报 Prompt |
| `backend/app/api/v1/reports.py` | `GET /reports/mastery`、`POST /reports/weekly`，只做参数/权限/Envelope |
| `backend/app/api/router.py` | include reports |
| `backend/app/models/enums.py` | `LLMCallScene.REPORT` |
| `backend/alembic/versions/0017_s5_6.py` | CHECK 扩展 |
| `docs/API.md` | §9 两个接口完整契约 |
| `docs/SCHEMA.md` | §8.4 scene 值集补 report |
| 测试 | `tests/test_report_service.py`、`tests/test_weekly_report.py`、`tests/test_reports_api.py`、`tests/test_report_migration.py`；改 3 个旧 head 测试 |

## 8. 测试计划（TDD，先红后绿）

1. **窗口/补零**：7/30/90 长度、非法 range、UTC 起止、空数据补 0。
2. **雷达**：模块含自身+后代、已评估均值、无评估 null、`kp_count/assessed_count`、固定 kp_id 排序。
3. **热力图**：level2 parent 归一 null、level3/4 父 id、未评估 null、`color_value=1−M_t`、`assessed`。
4. **趋势**：四项计数 + net、跨天补零、笔记软删排除、review done_at 只取当前快照。
5. **周报统计**：totals/active_days/avg_mastery/weak_modules/weak_kps、空数据判定。
6. **数字校验**：允许集合、日期拆分、小数/负数、列表序号忽略、无数字报告、非法数字。
7. **周报适配器**：Prompt 渲染、LLM mock 成功、第一次非法→重试成功、重试耗尽抛错、LLMError 包装、attempts 正确。
8. **API**：GET 结构、range 非法 422、401/403、POST mock LLM/空数据、500 错误壳。
9. **迁移**：`0017_s5_6` head、CHECK 包含 report、降级恢复。
10. **用户隔离**：GET/POST 的所有 SQL 都显式带 `user_id`；`FakeSession` 编译语句断言 `notes.user_id/review_items.user_id/mistakes.user_id/mastery.user_id` 均出现。
11. 全量 `pytest` 必须绿；前端不新增测试（本卡不改前端），但跑既有 296 条与 build 确认无回归。

## 9. 真机验收

### 9.1 环境

- 真实 PostgreSQL 16，迁移到 `0017_s5_6 (head)`。
- 专用学生：优先用有数据的 user 50（10 条 mastery、4 篇笔记、38 条错题、2 份已提交试卷）；空数据用 user 62。
- LLM Key 已配置（DashScope qwen-plus）；真实调用一次周报。

### 9.2 GET 验收

- `GET /api/v1/reports/mastery?range=30d`：
  - `trend` 30 个点、日期连续；
  - `subjects` 只有数学；`modules` 11 个 level2 模块；
  - `heatmap` 节点数 = level2+3+4 总数，level2 `parent_id=null`；
  - 模块 `mastery` 与 SQL 手算均值一致（抽 1 个模块）；
  - 未评估节点 `mastery_t=null`、`color_value=null`；
  - `range=7d/90d` 趋势长度正确，非法 range 422。

### 9.3 周报验收

- `POST /api/v1/reports/weekly` 真实 LLM：
  - 200，`generated_by=llm`，`report_md` 非空；
  - 脚本重新提取 `report_md` 数字，逐个在 `stats` 的数值集合中命中；
  - `validation.ok=true`、`invalid_numbers=[]`；
  - `llm_call_logs` 有 `scene='report'` 的成功记录（真实调用）。
- 空数据 user 62：200，`generated_by=empty`，无 LLM 调用，固定文案，`attempts=0`。
- 真实 HTTP 401/403；LLM 失败由单测 mock 覆盖（不故意破坏真实 Key）。

### 9.4 证据

`.sdd/s5-6/acceptance-evidence.md` 保存：
- 实际 curl/HTTP 响应节选；
- GET 趋势长度、模块数、节点数、抽样模块手算；
- 周报全文、数字校验结果、llm_call_logs 查询结果；
- 空数据响应；
- 全量测试与前端 build 输出。

## 10. 风险与边界

- **无历史快照**：`reviews_done` 只反映当前行，重开后丢失；`mastered_mistakes` 按当前状态回算；不提供复习完成率/薄弱点变化。
- **UTC 日界**：与 S4-8 一致，但与 S5-5 复习清单的本地日界不同；文档必须写明。
- **软删笔记**：删除后历史 `new_notes` 会减少；不保留删除快照。
- **热力图节点多**：真实 107 个 level2–4 节点，S5-7 需注意 Treemap 性能；本卡不截断。
- **周报成本**：同步 POST 每次真实调用 LLM，不缓存不落库；S5-7 应避免页面自动重复请求。
- **数字校验只覆盖阿拉伯数字**：中文数字、Markdown 序号不参与；Prompt 明确要求阿拉伯数字且禁用有序列表。
- **LLM 严格失败**：重试耗尽直接 500，不用确定性模板伪造 LLM 报告；空数据是唯一非 LLM 分支。
- **多学科**：接口已按 subjects 分组，但当前库只有数学；S5-7 只展示已实现学科。

## 11. 文档同步

- `docs/API.md §9`：两个接口的完整入参/出参/口径/错误。
- `docs/SCHEMA.md §8.4`：`llm_call_logs.scene` 值集补 `report`；无新表。
- `docs/PROGRESS.md`：S5-6 完成、测试计数、验收结论、已知边界。
- `docs/DECISIONS.md`：新增 D-063（报告口径、周报校验、UTC、无历史指标、scene）。
- `docs/AGENTS.md §9.2/§9.6`：报告口径锚点。
- `docs/AI协作开发实施计划.md` §S5-6 勾选。
- `docs/plan/s5-6-report-weekly.md`：确认后写。
- `.env.example` / `requirements.txt`：本卡无新增配置/依赖。

## 12. 待用户确认的最后一个点

- 周报是否允许「无数据时确定性空文案」而不调用 LLM：本 spec 选择允许，`generated_by="empty"`，不伪造学习建议；如不希望出现非 LLM 分支，需要改为仍然调用 LLM。