# S4-8 错题统计看板 — 设计 spec

> 任务卡：`docs/AI协作开发实施计划.md` §S4-8（阶段 4 收尾卡，milestone `m3-mistake-graph-done`）
> 方案出处：`docs/个性化学习智能体-毕业设计完整方案.md` §6.8（报告中只取「错题统计」部分）
> 日期：2026-11-04

## 1. 背景与目标

S4-1～S4-7 把「题目 → 错题 → 错因 → 知识图谱 → 掌握度」这条数据链打通了，但目前没有一个地方能把它们**汇总给人看**：错题本页只能逐条翻，`/mistakes/stats` 只返回三个数字数组（状态/错因/TOP10），没有时间维度，也不带掌握度。

本卡目标：给出一条 `GET /stats/overview` 聚合接口 + 一个 `/stats` 页面，把**状态分布、错因分布、知识点 TOP10（带掌握度）、近 N 天趋势**四块一次讲清楚。

### 1.1 非目标

- 不做掌握度雷达图/热力图/学习轨迹折线（§6.8 学习报告，归 S5-6；API.md 的 `GET /reports/mastery` 也留给它）
- 不做周报 LLM 文本、思维导图（S5-6）
- 不做老师/家长看学生（错题是本本人私有数据，权限口径不变）
- 不新增表、不改迁移、不加依赖

### 1.2 与 S4-2 的边界（重要）

`GET /api/v1/mistakes/stats`（S4-2）已经在做 SQL 聚合，返回 `by_status` / `by_cause` / `top_kps`。本卡**不复用也不改它**：

| | `/mistakes/stats` | `/stats/overview`（本卡） |
|---|---|---|
| 用途 | 错题页顶部三条小统计 | 看板页四块图 |
| 时间维度 | 只有 `created_from/to` 边界 | `range` 窗口 + 按天补零趋势 |
| 掌握度 | 无 | TOP KP 带折算 `M_t` |
| 解释性计数 | 无 | `with_kp` / `mastery_rows`（解释为什么 TOP 柱少） |

理由：错题页只需要那三个数组，让它顺带返回趋势会变胖；看板需要窗口语义和解释性数字。两者口径都写进 API.md，数字必须能交叉核对上。

## 2. 范围

| 层 | 内容 |
|---|---|
| 后端 | `services/stats_service.py`（5 条 SQL 聚合 + 补零）、`api/v1/stats.py`、`schemas/stats.py` |
| 契约 | API.md 新增 `GET /api/v1/stats/overview` |
| 前端 | `/stats` 页（仅 student）、`api/stats.ts`、`types/stats.ts`、`views/stats/useStatsCharts.ts`（纯函数）、`views/stats/Stats.vue`、路由与导航 |
| 数据 | 无新表、无迁移 |

## 3. 契约变更

### 3.1 API.md 新增（并入 §4.7 统计）

```markdown
### GET /api/v1/stats/overview
- 权限：`student`（teacher/parent/admin → 403/40300）
- 类型：同步
- 入参：`range`（可选，`7d`｜`30d`｜`90d`，默认 `30d`；其他值 422/42200）
- 出参：`Envelope[StatsOverviewOut]`

  ```json
  {
    "range": {"key": "30d", "from": "2026-10-06", "to": "2026-11-04"},
    "summary": {"total": 34, "pending": 33, "corrected": 1, "mastered": 0,
                "analyzed": 34, "with_kp": 3, "mastery_rows": 5},
    "by_status": [{"status": "待订正", "count": 33}, {"status": "已订正", "count": 1}, {"status": "已掌握", "count": 0}],
    "by_cause":  [{"cause_type": "概念不清", "count": 11}],
    "top_kps":   [{"kp_id": 197, "kp_name": "同角三角函数基本关系", "count": 1, "mastery": 0.144}],
    "trend":     [{"date": "2026-11-03", "new_mistakes": 34, "mastered": 0}]
  }
  ```

- 口径：
  - `range` 窗口按 `mistakes.created_at` 过滤（`[今天-N+1 天 00:00 UTC, 现在]`），`summary` / `by_status` / `by_cause` / `top_kps` 全部同窗口
  - `by_status` **恒 3 行**（无该状态补 0），避免前端做占位
  - `by_cause` 只列有诊断的错因，按 `count DESC, cause_type ASC` 定序；`unknown` 照常出现
  - `top_kps` 最多 10 条，`count` = 去重错题数；`mastery` = S4-7 的折算 `M_t`，**无行 = `null`（未评估）**
  - `summary.analyzed` = 有错因诊断的错题数；`with_kp` = 挂了知识点的错题数；`mastery_rows` = 本人掌握度行数——这三个是**解释性数字**，用于解释 "TOP 柱为什么只有 3 根"
  - `trend` 按天**补零**，窗口内每天一行（`7d`/`30d`/`90d` 分别 7/30/90 个点）；`new_mistakes` = 当天新增错题数；`mastered` = **回算累计**：当前状态为「已掌握」且 `last_review_at` 落在该天及之前的错题数——不是历史快照，状态回退会让历史曲线跟着变
- 错误：401/40100、403/40300、422/42200
```

## 4. 后端设计

### 4.1 服务 `app/services/stats_service.py`

```python
RANGES = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_RANGE = "30d"

@dataclass(frozen=True, slots=True)
class Window:
    key: str
    days: int
    start: datetime      # 今天-(days-1) 的 00:00 UTC
    end: datetime        # 现在
    dates: list[date]    # 长度为 days，升序

def build_window(range_key: str, *, now: datetime | None = None) -> Window
def fill_days(rows: Mapping[date, int], dates: Sequence[date]) -> list[tuple[date, int]]
def overview(session, *, user_id: int, range_key: str = DEFAULT_RANGE, now: datetime | None = None) -> StatsOverviewOut
```

SQL 固定 5 条（全部 `GROUP BY`，Python 只做补零与 DTO 组装）：

1. `mistakes` 按 `status` 分组 + 总数
2. 两条 `scalar` 计数：`select count(distinct MistakeAnalysis.mistake_id)`（有诊断）与 `select count(distinct Mistake.id).join(QuestionKp)`（挂 KP）——都是单行聚合，不是逐条查询
3. `mistake_analyses ⋈ mistakes` 按 `cause_type` 分组
4. `question_kps ⋈ mistakes ⋈ knowledge_points` 按 `kp_id` 分组、`limit 10`
5. `mistakes` 按 `date_trunc('day', created_at)` 分组（新增）+ `mistakes` 按 `date_trunc('day', last_review_at)` 分组且 `status='已掌握'`（回算）

第 4 条之后用一次 `mastery` IN 批查拿 `M_t`（复用 `mastery_service.decayed_mastery`），**不在循环里查库**。

`build_window` 的 `start` 用 UTC 零点：`now` 归一到 `date`，往前推 `days-1` 天，取 `datetime.combine(..., tzinfo=utc)`。

### 4.2 Schema `app/schemas/stats.py`

```python
class StatsRangeOut(BaseModel): key: str; from_: date (alias "from"); to: date
class StatsSummaryOut(BaseModel): total/pending/corrected/mastered/analyzed/with_kp/mastery_rows: int
class StatusCountOut(BaseModel): status: str; count: int
class CauseCountOut(BaseModel): cause_type: str; count: int
class KpTopOut(BaseModel): kp_id: int; kp_name: str; count: int; mastery: float | None
class TrendPointOut(BaseModel): date: date; new_mistakes: int; mastered: int
class StatsOverviewOut(BaseModel): range/summary/by_status/by_cause/top_kps/trend
```

`from` 是 Python 关键字：字段名 `from_`，配 `Field(alias="from")`；FastAPI 的 `response_model` 默认 `by_alias=True`，出参 JSON 里就是 `from`。构造时用 `from_=...`（`model_config` 不需要 `populate_by_name`）。

### 4.3 路由 `app/api/v1/stats.py`

`prefix="/stats"`、`tags=["stats"]`；`GET /overview`，`range: Literal["7d","30d","90d"] = Query("30d")`，`require_role("student")`，`Envelope` 组装，≤30 行。注册到 `api/router.py`。

非法 `range` 走 FastAPI 校验 → 全局 handler → `422/42200`（与全站一致，不自己抛）。

## 5. 前端设计

| 文件 | 职责 |
|---|---|
| `src/types/stats.ts` | 与出参一一对应的 TS 类型 |
| `src/api/stats.ts` | `fetchStatsOverview(range: StatsRange): Promise<StatsOverview>` |
| `src/views/stats/useStatsCharts.ts` | 纯函数：`fillDays(dates, rows)`、`causeOption(data)`、`topKpOption(data)`、`trendOption(data)`、`summaryCards(data)` |
| `src/views/stats/Stats.vue` | 页面：range 三档切换、摘要卡、三张图、空态与「未挂知识点」提示 |
| `src/router/index.ts` | 新增 `/stats`：`meta: { title: '统计', nav: 'stats', roles: ['student'] }` |
| 侧栏导航 | 与 `/graph` 同级加「09 统计」 |

**图表**（全部 ECharts，复用现有 6.1.0 按需引入，不加依赖）：

1. **错因分布**：环形饼图；`unknown` 用灰色并标注「未诊断」
2. **知识点 TOP10**：横向条形图；柱子颜色沿用 S4-7 掌握度四档（`null` 灰 / `<0.4` 红 / `0.4–0.7` 黄 / `≥0.7` 绿），label 显示 `错题数 · 掌握度 0.14`
3. **趋势**：折线双系列——`new_mistakes`（蓝）+ `mastered` 累计（绿，虚线）；`mastered` 全 0 时不画线，改在图右上角标注「窗口内暂无已掌握错题」
4. **摘要卡**：错题总数 / 待订正 / 已订正 / 已掌握 4 个数，下方小字「34 条中 34 条已诊断 · 3 条挂知识点」

**空态**（不编数据）：

| 情况 | 表现 |
|---|---|
| `total == 0` | 整页空态「窗口内没有错题」+ 跳错题录入 |
| `by_cause` 空 | 饼图位置显示「还没有错因诊断」 |
| `top_kps` 空 | 柱图位置显示「还没有错题挂上知识点」 |
| `top_kps` 每条 `count` 全相同 | 柱高一样是正常形态（3 条错题共挂 5 个 KP，各计 1 次），不额外做“去并列”处理 |
| `summary.with_kp < summary.total` | 柱图下方一行灰字「其余 N 条错题未关联知识点，因此不在图上」 |

**性能**：单次请求聚合，前端一次渲染 3 张图；不轮询、不自动刷新。

## 6. 测试

`backend/tests/test_stats_service.py`（FakeSession，断言编译 SQL 含 `user_id` 与窗口边界）：

1. 窗口构造：`7d/30d/90d` 的 `start`/`dates` 长度与首尾；跨月/跨年正确
2. 补零：窗口 30 天、只有 1 天有数据 → 30 个点、29 个 0
3. `by_status` 恒 3 行且顺序固定（`待订正 → 已订正 → 已掌握`）
4. `by_cause` 排序（count 降序、并列按 cause_type）
5. `top_kps` 上限 10 且 `mastery` 无行时为 `None`
6. 全部 SQL 都带 `mistakes.user_id = :user_id`（编译后断言），窗口边界出现在 SQL 里
7. `mastered` 回算：只统计 `status='已掌握'` 且按天累计
8. 非法 `range_key` → `InvalidParamError`（service 层防御，路由层已被 Literal 拦住）

`backend/tests/test_stats_api.py`：

1. 未登录 401、教师 403
2. `range=abc` → 422/42200
3. `range` 透传与默认值（monkeypatch service）
4. 出参 `range.from` 字段名正确（不是 `from_`）

前端：

- `useStatsCharts.spec.ts`：`fillDays` 跨月补零、`causeOption` 数据映射与 `unknown` 灰色、`topKpOption` 掌握度四档颜色 + `null` 灰 + 空数组、`trendOption` 全 0 mastered 时不加系列、`summaryCards` 文案
- `Stats.spec.ts`：mock `api/stats` 与 `echarts/*`（照 `Graph.spec.ts` 的 `vi.hoisted` 做法）；断言摘要数字渲染、空态文案、range 切换重新请求

## 7. 验收口径（真机，学生 50）

实测基线（2026-11-04，30d 窗口）：

| 项 | 期望 |
|---|---|
| `summary.total` | 34 |
| `pending / corrected / mastered` | 33 / 1 / 0 |
| `analyzed` | 34 |
| `with_kp` | 3 |
| `mastery_rows` | 5 |
| `by_cause` | 概念不清 11 / 计算失误 6 / 知识遗忘 5 / 时间不足 4 / 方法不当 4 / 审题偏差 3 / unknown 1（和 34 条诊断对得上） |
| `top_kps` | **5 条**：KP 120 数列 / 128 集合的基本运算 / 160 等差数列 / 197 同角三角函数基本关系 / 204 通项公式与性质，每条 `count=1`、`mastery` 见 S4-7 实测（上限 10 不触发） |
| `trend` | 30 个点，只有 `2026-11-03` 非零（34），`mastered` 全 0 |

验收步骤：

1. `GET /api/v1/stats/overview`（学生 50）→ 数字与上表一致
2. 与 `GET /api/v1/mistakes/stats` 交叉核对：`total`、`by_cause` 逐类一致、`top_kps` 一致
3. `range=7d` → 34 个点变 7 个点、`2026-11-03` 仍有值；`range=90d` → 90 个点
4. 教师账号 → 403；`range=abc` → 422
5. `/stats` 页面：三张图正常渲染、range 切换生效、柱图下出现「其余 31 条错题未关联知识点」
6. 空态：用一个没有错题的账号（教师不行，需学生账号 `s43_accept_20261103` 有数据；另找/临时建空账号需谨慎）——**若找不到空账号，本条标为未验证**，不编数据

## 8. 风险与已知限制

- **TOP 柱少且全等高是数据问题，不是代码问题**：34 条错题只有 3 条挂知识点（共 5 个 KP），所以图上 5 根柱子、每根都是 1。看板如实呈现 + 解释性提示（`with_kp=3`），不补假数据；要改善得回头看 S4-1 的知识对齐链路。
- **趋势只有 1 个非零点**：44 条错题的 `created_at` 集中在 11-02～11-03，30d 窗口里只有一天有新增。演示时折线几乎是平的——这是真实数据形态。
- **`mastered` 是回算不是快照**：没有状态变更历史表，只能按"当前状态 + `last_review_at`"反推。错题答错回退时，历史曲线会跟着变低。API.md 要写明。
- **不跨用户**：老师看不到学生看板（与 S4-2 权限口径一致），若答辩要演示"教师视角统计"，需另开卡（S4-8 卡没要求）。
- **时区**：窗口与按天分桶一律 UTC；`date_trunc` 在 PG 上按 `UTC` 语义执行（连接已设 UTC）。中国用户看到的"今天"可能差 8 小时，属既有口径（全站 UTC）。
- `range` 只支持三档固定值，不支持自定义区间——等真有需求再加。

## 9. 文档同步

- `docs/API.md`：新增 §4.7 统计（`GET /api/v1/stats/overview`），并在 `GET /api/v1/mistakes/stats` 备注里加一句「看板聚合见 `/stats/overview`」
- `docs/PROGRESS.md`：S4-8 打勾、最近完成、口径与实测数字、milestone 说明
- `docs/DECISIONS.md`：D-051（为什么新开接口不复用、回算累计的口径、UTC 分桶、TOP 柱少如实呈现）
- `README.md`：加「统计看板」一段（入口、range、已知数据限制）

## 10. 交付物清单

后端：`app/services/stats_service.py`、`app/schemas/stats.py`、`app/api/v1/stats.py`、`app/api/router.py`、`tests/test_stats_service.py`、`tests/test_stats_api.py`。

前端：`src/types/stats.ts`、`src/api/stats.ts`、`src/views/stats/useStatsCharts.ts`、`src/views/stats/Stats.vue`、`src/views/stats/useStatsCharts.spec.ts`、`src/views/stats/Stats.spec.ts`、`src/router/index.ts`、侧栏导航组件。

文档：上述四份 + `.sdd/s4-8/`（acceptance-evidence / progress）。

## 11. 已确认决策（用户，2026-11-04）

1. **接口落点**：新建 `GET /api/v1/stats/overview`（`api/v1/stats.py`），不动 `/mistakes/stats`；看板只调新接口。
2. **时间维度**：新增错题折线 + 已掌握累计（回算，如实标注口径）。
3. **知识点维度**：TOP10 错题数 + 掌握度值；未挂知识点的错题给提示，不补数据。（实测为 5 个 KP、各 1 条，柱高等高属真实形态）
4. **页面入口**：新页 `/stats`，侧栏「统计」，仅 student 可见。
5. **`/reports/mastery` 与掌握度雷达**：留给 S5-6 学习报告，本卡不做。
6. **收尾**：验收通过后本地打 tag `m3-mistake-graph-done`（用户 push 时 `--tags`）。