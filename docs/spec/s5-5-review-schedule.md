# S5-5 复习调度 + 每日清单（spec）

> 任务卡：`docs/AI协作开发实施计划.md` §S5-5。产出 `review_items` 表、`services/review_service.py`、定时任务、`api/v1/review.py`。
> 状态：**待用户确认**（2026-11-14）。确认后才写 plan。
> 范围：只做后端调度与接口；`views/review/Today.vue` 留给 S5-7。

## 1. 目标与非目标

### 1.1 目标

1. 每个学生每天有一份**可执行、有上限**的复习清单：按掌握度衰减、到期时间、考纲权重排序。
2. 清单项按知识点生成，指向可操作资源：优先未掌握错题，否则该知识点的一道题。
3. 清单总量硬上限默认 35 分钟；装不下的顺延到明天，响应明示截断数量。
4. `M_t < 0.4` 的弱项天天作为候选，并在排序中优先；但不豁免时长上限。
5. 支持完成 / 跳过 / 稍后三种操作；当天已处理的项刷新不重新出现。
6. 每日凌晨自动生成 + 学生手动刷新，二者幂等。
7. 自动化测试覆盖纯函数、service、API、scheduler；真机做连续 7 天模拟，检查清单随掌握度合理变化。

### 1.2 非目标（留给后续卡）

- 不做复习清单页（`/plan` 仍 ComingSoon，S5-7 接接口）。
- 不生成 `ref_type=note` 的复习项；note 入口由 S5-7 另行展示。
- 不给 `review_items` 加 `status` 列，不保留每日历史快照。
- 完成/跳过**不直接写掌握度**；掌握度只由真实作答（S5-4 交卷、`POST /mistakes/{id}/review`）产生。
- 不做推送/邮件提醒、不做多用户时区偏好（统一 `Asia/Shanghai`，可配置）。
- 不把调度器嵌进 FastAPI/ARQ；独立进程运行。

## 2. 用户已确认的决策（2026-11-14）

| # | 决策 | 选择 |
|---|---|---|
| D1 | 本卡范围 | **仅后端调度与接口**；前端清单页归 S5-7 |
| D2 | 清单粒度 | **一 kp 一条待办行**，`UNIQUE(user_id, kp_id)`，重复刷新更新同一行 |
| D3 | 待办指向 | **错题优先，回退题目**：有未掌握错题指向最近错题，否则指向该 kp 的一道题 |
| D4 | 时长与弱项冲突 | **硬上限 35 分钟**，弱项靠优先级排序；装不下顺延，响应给 `truncated_count` |
| D5 | 完成语义 | done/skip 只写 `done_at`，**不动掌握度**；later 把 `due_at` 顺延到明天；不加 status 列 |
| D6 | 接口面 | `GET /review/today`、`POST /review/refresh`、`POST /review/items/{id}/done|skip|later` 共 5 个 |
| D7 | 调度部署 | **独立 `python -m app.scheduler` 进程**，每天 00:05（`Asia/Shanghai`），PG advisory lock 防重复 |
| D8 | 新依赖 | **批准新增 APScheduler**（固定版本，随 `requirements.txt` 锁定） |
| D9 | GET 语义 | `GET /review/today` **只读**，不隐式写库；S5-7 进入页面先调 refresh |

## 3. 数据模型：`review_items`（迁移 `0016_s5_5`）

按 SCHEMA §6.4 落表，并补三处契约（先改 SCHEMA，再写代码）：

| 字段 | 类型 | 可空 | 约束/默认 | 说明 |
|---|---|---|---|---|
| id | BIGINT | 否 | Identity PK | |
| user_id | BIGINT | 否 | FK `users.id` ON DELETE CASCADE | 学生 |
| kp_id | BIGINT | 否 | FK `knowledge_points.id` ON DELETE CASCADE | 知识点 |
| ref_type | TEXT | 否 | `CHECK ref_type IN ('note','question','mistake')` | 多态引用类型；本轮只写 question/mistake |
| ref_id | BIGINT | 否 | — | 对应 `questions.id` / `mistakes.id`；**多态引用不加外键** |
| due_at | TIMESTAMPTZ | 否 | — | 该复习项应当出现的时刻（本地日界 00:00 或 mastery 到期时刻） |
| interval_days | INTEGER | 否 | `CHECK 1 <= interval_days <= 30` | 本次调度间隔，来自 S4-7 `review_interval_days` |
| priority | NUMERIC(5,4) | 是 | `CHECK priority IS NULL OR (0 <= priority <= 1)` | 生成时算好；读取时按当前 M_t 重算展示值 |
| done_at | TIMESTAMPTZ | 是 | — | 完成/跳过时间；NULL = 未处理 |

索引/约束：

- **`uq_review_items_user_kp (user_id, kp_id)` 唯一**：一 kp 一条待办，刷新幂等；SCHEMA §6.4 原先未写唯一键，本卡补上。
- `ix_review_items_user_due (user_id, due_at)`：按人取今日/逾期。
- `ix_review_items_user_done (user_id, done_at)`：取未处理项。
- 不加 `created_at/updated_at`（SCHEMA 无该列）；不加 `status`（D5）。
- `ref_id` 无外键：题目/错题被硬删后行仍保留，接口返回 `ref_available=false`，不 500。

枚举：`ReviewRefType(StrEnum)` 放 `app/models/enums.py`（`NOTE/QUESTION/MISTAKE`），CHECK 文本由 `in_check()` 生成（项目统一 D-021）。

## 4. 调度算法（`services/review_service.py`）

### 4.1 时区与日界

- 统一使用 `settings.review_timezone`（默认 `Asia/Shanghai`）；`now` 统一为 aware UTC。
- `local_today = now.astimezone(tz).date()`；`day_start = 本地 00:00`；`next_start = 次日 00:00`（转 UTC 存储）。
- 所有“今天”的判断都用本地日界，不用 UTC 日界。

### 4.2 候选条件

对本人每条 `mastery` 行（join 知识点拿 `name/subject_id/exam_weight`）：

```
days = max(0, (now - last_practice_at).total_seconds() / 86400)
M_t  = decayed_mastery(M, S, days)          # 复用 S4-7
due  = mastery.due_at or now
low  = M_t < 0.4
candidate = low or due < next_start         # 到期（含逾期）或弱项
```

- `last_practice_at` 为空按 `days=0`。
- 同一天一个 kp 最多一条；已有行不重复建。
- 没有任何 mastery 行的用户返回空清单，不报错。

### 4.3 优先级

```
overdue_days = max(0, (now - due).total_seconds() / 86400)
overdue      = min(1, overdue_days / max(interval_days, 1))
priority     = 0.5*(1 - M_t) + 0.3*overdue + 0.2*(exam_weight or 0.5)
priority     = round(clamp(priority, 0, 1), 4)
```

- `exam_weight` 用知识点原值（当前库 0.5–1.0），NULL 回退 0.5。
- 排序：`priority` 降序 → `M_t` 升序 → `kp_id` 升序（保证确定性）。

### 4.4 资源选择

只对候选 kp 批量查询，禁止循环查库：

1. **错题优先**：本人该 kp 的错题，`status IN ('待订正','已订正')`（排除已掌握）；排序 `待订正` 先、`last_review_at/created_at` 倒序、id 倒序；取第一条 → `ref_type='mistake'`。
2. **回退题目**：该 kp 的 `question_kps` join `questions`，按 `question_kps.weight` 降序（NULL 最后）、`difficulty` 升序、`id` 升序取第一道 → `ref_type='question'`。
3. 都没有 → 该候选跳过，`skipped_no_ref += 1`。

`ref_title` 取资源题干的纯文本摘要（最多 120 字，换行压成空格）；错题取关联题目的题干。输出同时给 `ref_available`：读取时资源仍存在为 true，被硬删为 false。

### 4.5 预估时长与上限装填

```
estimated_minutes = 3 + difficulty   # ref_type=question
                    4 + difficulty   # ref_type=mistake
                    # note 本轮不生成；若未来启用按 3 + difficulty
```

- 默认 `cap_minutes = settings.review_daily_minutes`（35），按优先级顺序装填；`total + estimate <= cap` 才加入。
- 至少保留 1 项（即使单项预估 > cap，最大 9 分钟，实际不会发生）。
- 装不下的候选/已有项：`due_at = next_start`（顺延到明天），计入 `truncated_count`；明天刷新时重新竞争。
- 弱项不豁免上限；只是 `0.5*(1-M_t)` 让它们排前面。

### 4.6 刷新（`refresh_user`，只 flush 不 commit）

1. 计算候选、优先级、资源、预估。
2. 读本人全部 `review_items` 建 `kp_id → row` 映射。
3. 逐候选处理：
   - 计算生效到期：`effective_due = due`；若 `low` 且 `due >= next_start`，则 `effective_due = day_start`（弱项当天就该出现）。
   - 无行：新建，`due_at=effective_due`。
   - 有行且 `done_at >= day_start`：**今天已完成，跳过**，不改不重开。
   - 有行且 `done_at` 为空或早于今天：更新 `ref_type/ref_id/due_at/interval_days/priority`，并清 `done_at`（跨天重开）。
4. 对“今天应出现”的项做上限装填；未入选者 `due_at=next_start`。
5. 非候选且 `due_at >= next_start` 的行保持不动。
6. 新建走 `INSERT ... ON CONFLICT (user_id,kp_id) DO UPDATE`（PostgreSQL upsert），避免双击刷新撞唯一键；已有行走 ORM 更新。
7. 返回 `ReviewTodayOut`（见 §5），`truncated_count` 本次实际顺延数。

**幂等**：同一天连续 refresh，未完成项内容与 `due_at` 不变；已完成项不重开；不会新增第二行。

### 4.7 读取（`get_today`，只读）

- 取本人 `done_at IS NULL AND due_at < next_start` 的行，join 知识点；按当前 M_t 重算 `mastery_t/priority/overdue_days/low_mastery`（不用库里的旧 priority）。
- 排序同 §4.3。
- **不写库**；若当天还没 refresh，可能为空或缺少新到期项，由 S5-7 进入页面时调 refresh。

### 4.8 操作（done / skip / later）

- 校验 `review_items.id + user_id`，不存在或不属于本人 → 404/40400 `"复习项不存在"`（不泄露他人数据）。
- `done` / `skip`：`done_at` 已有值 → 409/40900 `"该复习项已完成"`；否则写 `done_at=now`。两者库内无区别，均不写掌握度。
- `later`：`done_at` 已有值 → 409；否则 `due_at=next_start`，`done_at` 保持 NULL。
- 返回更新后的 `ReviewItemOut`。

## 5. 接口（先改 `docs/API.md §9`，再写代码）

全部 `student` 权限（`require_role("student")`）。统一 `Envelope`，错误码沿用 S0-5。

### 5.1 `GET /api/v1/review/today`

- 类型：同步、只读
- 入参：无
- 出参：

```json
{
  "date": "2026-11-14",
  "timezone": "Asia/Shanghai",
  "items": [],
  "item_count": 0,
  "total_minutes": 0,
  "cap_minutes": 35,
  "truncated_count": null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| date | string | 本地日期 `YYYY-MM-DD` |
| timezone | string | 生效时区 |
| items | array | `ReviewItemOut`，排序见 §4.3 |
| item_count | int | items 长度 |
| total_minutes | int | 各项 `estimated_minutes` 之和 |
| cap_minutes | int | 当前配置上限 |
| truncated_count | int? | **GET 恒为 null**（不知道上次刷新截断数）；refresh 返回实际数 |

`ReviewItemOut`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | review_items.id |
| kp_id / kp_name / subject_id | int / string / int | 知识点 |
| ref_type | string | `note` / `question` / `mistake` |
| ref_id | int | 多态引用 id |
| ref_title | string? | 题干摘要 |
| ref_available | bool | 资源是否仍存在 |
| due_at | string | ISO-8601 UTC |
| interval_days | int | 1–30 |
| priority | number | 0–1，4 位 |
| estimated_minutes | int | 预估 |
| mastery | number | 原始 M，3 位 |
| mastery_t | number | 衰减后 M_t，3 位 |
| stability | number | S，2 位 |
| attempts | int | 作答次数 |
| overdue_days | number | 逾期天数，2 位；未到期 0 |
| low_mastery | bool | `M_t < 0.4` |
| done_at | string? | 完成/跳过时间；today 中恒 null（只返回未处理项） |

- 空清单 200。
- 不因未 refresh 报错。

### 5.2 `POST /api/v1/review/refresh`

- 类型：同步；按当前用户刷新并提交事务
- 入参：无
- 出参：同上；`truncated_count` 为本次实际顺延数
- 行为：幂等；当天已完成的项不重开
- 无 mastery 行 → 200 空清单

### 5.3 `POST /api/v1/review/items/{item_id}/done`

### 5.4 `POST /api/v1/review/items/{item_id}/skip`

### 5.5 `POST /api/v1/review/items/{item_id}/later`

- 权限：student，仅本人
- 入参：无 body
- 出参：`ReviewItemOut`
- 错误：
  - 404/40400 `"复习项不存在"`
  - 409/40900 `"该复习项已完成"`（done/skip/later 对已完成项）
  - 401/40100 未登录；403/40300 非 student

## 6. 定时任务（`backend/app/scheduler.py`）

- 独立进程：`cd backend && python -m app.scheduler`；`--once` 只跑一次后退出（验收/手动补跑）。
- `BlockingScheduler(timezone=ZoneInfo(settings.review_timezone))`，`CronTrigger(hour=0, minute=5, timezone=tz)`；`coalesce=True`、`max_instances=1`、`misfire_grace_time=3600`。
- 每次运行：
  1. 取 session，`SELECT pg_try_advisory_lock(5505)`；抢不到 → 记 INFO 并跳过本次。
  2. `SELECT DISTINCT user_id FROM mastery` 取学生（有掌握度即可；不 join users 角色，避免漏掉历史数据）。
  3. 每个用户一个 `SessionLocal` 事务：`refresh_user` → `commit`；单用户异常 `rollback` + ERROR 日志，继续下一个。
  4. `finally` `pg_advisory_unlock(5505)`；输出 `{"users": n, "items": m, "failed": k}`。
- 不做 FastAPI lifespan 启动；Docker/部署阶段再加 scheduler 服务。
- 配置：
  - `review_timezone: str = "Asia/Shanghai"`
  - `review_daily_minutes: int = 35`（10–120 校验）
  - 同步 `.env.example`。
- 依赖：`apscheduler==3.11.3`（2026-11-14 PyPI 最新稳定版；安装后跑 `pip show` 复核）。

## 7. 文件与分层

| 层 | 文件 |
|---|---|
| 模型 | `backend/app/models/review_item.py` |
| 枚举 | `backend/app/models/enums.py`（`ReviewRefType`） |
| 迁移 | `backend/alembic/versions/0016_s5_5.py` |
| schema | `backend/app/schemas/review.py` |
| service | `backend/app/services/review_service.py`（纯函数 + DB 用例） |
| API | `backend/app/api/v1/review.py` + `app/api/router.py` |
| 调度 | `backend/app/scheduler.py` |
| 配置 | `backend/app/core/config.py`、`.env.example`、`backend/requirements.txt` |
| 测试 | `tests/test_review_migration.py`、`test_review_service.py`、`test_review_api.py`、`test_review_scheduler.py` |
| 验收 | `.sdd/s5-5/review_check.py`、`acceptance-evidence.md` |

## 8. 测试计划（TDD，先红后绿）

1. **迁移**：列集合、`ref_type` CHECK、`interval_days` CHECK、`priority` 精度 (5,4)、唯一键 `uq_review_items_user_kp`、索引、FK CASCADE、`alembic head == 0016_s5_5`；更新 S5-4 迁移测试的 head 断言。
2. **纯函数**：
   - `overdue_ratio`：未到期/当天/超期/interval=1/上限 1。
   - `review_priority`：M_t=0 到期 → 1.0；M_t=1 无逾期 → 0.2*weight；weight NULL 回退。
   - `estimated_minutes`：question/mistake 随 difficulty 变化。
   - `is_candidate`：低掌握未来到期也候选；M_t≥0.4 且未到期不候选。
   - `select_capped`：装填顺序、边界、至少 1 项、截断数、总分钟。
3. **service（FakeSession）**：
   - 新建行、字段正确、不 commit；
   - 同一天 refresh 幂等；当天 done 不重开；
   - 昨天 done 且仍弱 → 重开；
   - 错题优先/回退题目/都无 → skipped_no_ref；
   - 超上限顺延并计 truncated；
   - `get_today` 只读、只返回未完成、排序；
   - done/skip/later 状态；重复 done 409；他人/不存在 404。
4. **API（FakeAuthSession）**：5 个接口 200；401；403（teacher）；空清单；404/409；Envelope 壳；refresh 提交。
5. **scheduler**：advisory lock 失败跳过；单用户异常隔离；成功计数；`--once` 参数（函数级）。
6. **真机 7 天模拟**（§9）。

## 9. 真机验收

### 9.1 环境

- 真实 PostgreSQL 16（迁移 head `0016_s5_5`）、后端 8000、`python -m app.scheduler --once`。
- 专用学生账号（`POST /auth/register` 创建，用户名带时间戳，不写真实个人信息），结束时保留数据供复查。
- 数据：现有题库 56 题/知识点 117、128、133、139 等；不新造题。

### 9.2 连续 7 天模拟

以“今天−6 … 今天”为 7 个本地日，逐日：

1. `mastery_service.record_attempts(..., now=day_start)` 模拟当日作答（s 轮换 0/0.5/1，难度 2–4），产生到期/衰减。
2. `review_service.refresh_user(session, user_id=..., now=day_start + 08:05)`，commit。
3. 断言：
   - 清单总分钟 ≤ 35；条数 ≥1（有候选时）；
   - `M_t < 0.4` 的 kp 在候选内；
   - 当天做了 done 后，同日再次 refresh 不重新出现；
   - 做 `later` 的项当天消失、次日出现；
   - 超上限项次日出现，`truncated_count` 与顺延数一致；
   - 优先级随 M_t 降低/逾期增加而上升（至少一组可验证的单调变化）。
4. 记录每天 `{date, items, total_minutes, truncated}` 到证据文件。

### 9.3 真 HTTP

- 启动后端，使用专用账号 token：
  - `POST /review/refresh` → 200，返回今日清单；再调一次，未完成项 id 不变（幂等）。
  - `GET /review/today` → 与 refresh 一致，且不再写库。
  - `POST /review/items/{id}/done` → 200；重复 → 409。
  - `POST /review/items/{id}/later` → `due_at` 为次日 00:00（本地）。
  - `GET /review/today`（done 后）不再含该项。
- `python -m app.scheduler --once` → 日志/输出 users/items，不重复建行。
- 真实库核对：`review_items` 行数、唯一键、`done_at`、`due_at` 时区。

### 9.4 证据

`.sdd/s5-5/acceptance-evidence.md`：命令、7 天表、真实数字、异常与修复；不写“应该”。

## 10. 风险与边界

- **硬上限截断弱项**：弱项不保证每天都进清单；响应 `truncated_count` + 次日优先作为补偿。这是 D4 的明确取舍。
- **清单完成不等于学会**：done/skip 不写掌握度，避免刷清单抬分；S5-7 的“完成两项 → 掌握度变化”必须通过真实作答实现，验收时按此解释。
- **GET 不隐式生成**：新用户/当天首次访问可能为空，S5-7 进入页面需先调 refresh；若 S5-7 希望 GET 自愈，另开卡改契约。
- **note 类型未用**：SCHEMA 枚举保留，S5-5 不生成；后续卡可加。
- **ref 资源删除**：`ref_available=false`，不自动换题；刷新时会重新选资源（若还有候选）。
- **多实例调度**：advisory lock 只防同一时刻重复；若一次运行跨越次日 00:05，下一次会等锁，`max_instances=1` 兜底。
- **用户规模**：逐用户 refresh，当前单机小规模；上千用户需改批处理/任务队列（后续卡）。
- **时区**：全局一个时区，不做用户级；跨时区学生按北京时间作息。

## 11. 文档同步

- `docs/SCHEMA.md §6.4`：补唯一键、CHECK、索引、`ref_id` 无外键、无 status 的语义。
- `docs/API.md §9`：写全 5 个接口的入参/出参/错误。
- `docs/PROGRESS.md`：当前状态、最近完成、验收数字、遗留。
- `docs/DECISIONS.md`：D-062（本卡口径）。
- `AGENTS.md §9.2`：新增复习调度条目；§9.6：新增 `review_service` 锚点。
- `docs/AI协作开发实施计划.md`：S5-5 勾选。
- `.env.example`：`REVIEW_TIMEZONE`、`REVIEW_DAILY_MINUTES`。
- `backend/requirements.txt`：APScheduler。
- 无前端改动、无 package.json 改动。