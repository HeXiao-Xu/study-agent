# S4-7 掌握度模型 + 更新服务 — 设计 spec

> 任务卡：`docs/AI协作开发实施计划.md` §S4-7（★关键路径）
> 公式出处：`docs/个性化学习智能体-毕业设计完整方案.md` §6.6
> 表结构出处：`docs/SCHEMA.md` §6.3（此前只有契约，未建表）
> 日期：2026-11-04

## 1. 背景与目标

S4-1～S4-6 已经产出「题目 → 错题 → 错因 → 关系图谱」这条链，但**没有任何地方回答"这个学生到底掌握了没有"**。S4-6 的图谱配色只能拿「错题数」当临时热力（D-049），S5-1 组卷的「掌握度匹配」项、S5-5 的每日清单、S4-8 的看板全都等这张表。

本卡目标：把方案 §6.6 的简化掌握度模型**落成可测的纯函数 + 一张表 + 两个接口**，并挂到既有的「错题复习」动作上，让掌握度是活的、有数据来源的，不是页面里编出来的数字。

### 1.1 非目标

- 不做 `answers` / `review_items`（S5 的表，本卡不提前建）
- 不做每日清单、优先级排序、总量控制（S5-5）
- 不做老师/家长看学生掌握度、不做看板（S4-8）
- 不引入 APScheduler（本卡没有定时任务，衰减是**读取时折算**）

## 2. 范围

| 层 | 内容 |
|---|---|
| 数据 | 新表 `mastery` + 迁移 `0013_s4_7` |
| 服务 | `app/services/mastery_service.py`：纯函数内核 + `record_attempts` / `recompute_user` / `list_mastery` |
| 挂载 | `mistake_service.record_review` 内更新掌握度（同事务） |
| 接口 | `POST /kp/mastery/recompute`、`GET /kp/mastery` |
| 图谱 | `GET /kp/graph/snapshot` 节点加 `mastery`，前端配色改为掌握度 |
| 证据 | `scripts/mastery_sim.py`（7 天模拟 + 参数敏感性），答辩可用 |

## 3. 契约变更（先改契约再写码）

### 3.1 SCHEMA.md §6.3 补三处口径（不改字段）

表名取 SCHEMA 原文的 `mastery`（不是复数），字段全部照原文，只补三处此前未定死的细节：

- `stability NUMERIC` → **`NUMERIC(6,2)`**（要存到 60.00，且 ×1.8 连续放大后仍需两位小数）
- `mastery` 的**初始值 = 0**：首次作答从 0 开始学（`M ← 0 + K_eff·(s−0)`），不引入"基础先验"
- **懒创建**：没有作答事件就没有行；「无行」对外语义是**未评估**，不是 0 掌握

### 3.2 API.md 新增两条（并入 §4.6）

```markdown
#### POST /api/v1/kp/mastery/recompute
- 权限：student（只重算本人）
- 类型：同步
- 说明：按时间序回放本人全部错题的「作答事件」重建掌握度。事件来源：每条错题按状态折算 s（待订正=0 / 已订正=0.5 / 已掌握=1），事件时间取 `last_review_at`，为空则取 `created_at`；难度取 `questions.difficulty`；一条错题挂 K 个知识点就产生 K 次同类事件。**覆盖式重建**：先删本人 `mastery` 全部行，再按时间序重算。
- 出参：`Envelope[{"events_replayed": 44, "rows_built": 13, "skipped_no_kp": 31}]`
- 备注：幂等（同数据跑两次结果一致）；只重建不新增事件来源，不做增量补偿
- 错误：401/40100、403/40300（非 student 角色无权）、422/42200

#### GET /api/v1/kp/mastery
- 权限：student（只读本人）
- 类型：同步
- 入参：`subject_id`（可选，int ≥1）、`page`/`page_size`（统一分页）、`sort_by`/`order`（白名单 `mastery` / `due_at` / `attempts` / `kp_id`，默认 `mastery ASC`）
- 出参：`Envelope[PageData[MasteryOut]]`，`MasteryOut = {kp_id, kp_name, subject_id, mastery, mastery_t, attempts, correct_cnt, stability, last_practice_at, due_at}`
- 备注：`mastery` 是库存原值；`mastery_t` 是**按当前时间折算**的有效掌握度 `M·exp(−Δt/S)`（无 `last_practice_at` 时等于 `mastery`）；只返回有行（已评估）的知识点
- 错误：401/40100、403/40300、422/42200
```

### 3.3 API.md §4.5 快照出参补字段

`GraphSnapshotNode` 增加 `mastery`（`float | null`，= 折算后的 `M_t`；无行 = `null`）。前端据此配色。

## 4. 后端设计

### 4.1 模型 `app/models/mastery.py`

照 `SCHEMA.md` §6.3 与一致性锚点（`models/user.py` 风格）：

```python
class Mastery(Base):
    __tablename__ = "mastery"
    id: BIGINT IDENTITY PK
    user_id: BIGINT FK users.id ON DELETE CASCADE, not null
    kp_id: BIGINT FK knowledge_points.id ON DELETE CASCADE, not null
    mastery: Numeric(4, 3), not null
    attempts: Integer, not null, server_default 0
    correct_cnt: Integer, not null, server_default 0
    stability: Numeric(6, 2), not null, server_default 2
    last_practice_at: TIMESTAMPTZ, nullable
    due_at: TIMESTAMPTZ, nullable
    updated_at: TIMESTAMPTZ, not null, server_default now(), onupdate now()
    __table_args__ = (
        UniqueConstraint("user_id", "kp_id", name="uq_mastery_user_kp"),
        Index("ix_mastery_user_due", "user_id", "due_at"),
    )
```

迁移 `0013_s4_7_mastery.py`：`down_revision = "0012_s4_5"`，只建表 + 2 个约束/索引，不动历史迁移。

### 4.2 公式内核（纯函数，全部可直接手推）

```python
K0 = 0.35
INITIAL_STABILITY = 2.0
STABILITY_GROW = 1.8
STABILITY_SHRINK = 0.5
STABILITY_MAX = 60.0
STABILITY_MIN = 1.0
INTERVAL_MIN_DAYS, INTERVAL_MAX_DAYS = 1, 30

def effective_k(difficulty: int) -> float      # K0 / difficulty
def next_mastery(m: float, s: float, k: float) -> float   # clamp(m + k*(s-m), 0, 1)
def next_stability(stability: float, s: float) -> float
def decayed_mastery(m: float, stability: float, dt_days: float) -> float   # m*exp(-dt/S)
def review_interval_days(stability: float, mastery_t: float) -> int        # clamp(round(S*M_t), 1, 30)
def next_state(state: MasteryState, *, s, difficulty, now) -> MasteryState
```

`MasteryState` 是不可变 dataclass（`mastery / attempts / correct_cnt / stability / last_practice_at / due_at`），DB 层只做「读 → 纯函数 → 写回」，所以四种验收场景全部可以脱离数据库断言。

**舍入**：入表前 `mastery` 保留 3 位小数（`NUMERIC(4,3)`），`stability` 保留 2 位；比较与断言都用这个精度，避免浮点误差在用例里打架。

**`s = 0.5`（半对）时 S 不变**——方案只给了答对/答错两条规则，半对按"没有增强也没有削弱记忆"处理，在 spec 与代码注释里都写出来。

**`correct_cnt` 只在 `s >= 1` 时 +1**，半对不计入答对次数（看板要能区分"做过"和"做对"）。

### 4.3 用例

```python
def record_attempts(session, *, user_id, kp_ids, s, difficulty, now=None) -> list[Mastery]
    # 懒创建：缺行则新手（mastery=0, attempts=0, correct_cnt=0, stability=2）
    # 同一时刻对多个 kp 复用同一个 now，保证 due_at 可比

def recompute_user(session, *, user_id, now=None) -> RecomputeResult
    # 1) 查本人 mistakes ⋈ questions(difficulty) ⋈ question_kps(kp_id)
    #    一条 SQL 取全量（禁止 N+1），event_at = last_review_at or created_at
    # 2) 按 (event_at, mistake_id, kp_id) 排序 → 逐事件 next_state 回放
    # 3) 覆盖式：先 delete 本人全部行 flush，再批量 insert
    # 4) 无 question_kps 的错题计入 skipped_no_kp

def list_mastery(session, *, user_id, subject_id=None, params, sort) -> Page
    # join knowledge_points 取 kp_name/subject_id，mastery_t 在当前时刻折算
```

- 一个用例一个事务：`record_attempts` 由调用方（`record_review`）统一 commit；`recompute_user` 自带 commit（它是完整用例）。
- 不做 N+1：回放前一次 SQL 取事件流，重建时一次 `DELETE` + 一次批量 `INSERT`。

### 4.4 挂载点

`mistake_service.record_review` 在 `mistake.last_review_at = now` 之后、`_commit(session)` 之前：

```python
kp_ids = session.scalars(select(QuestionKp.kp_id).where(QuestionKp.question_id == mistake.question_id)).all()
if kp_ids:
    difficulty = session.scalar(select(Question.difficulty).where(Question.id == mistake.question_id)) or 3
    mastery_service.record_attempts(session, user_id=user_id, kp_ids=kp_ids,
                                    s=1.0 if correct else 0.0, difficulty=difficulty)
```

- 答对 `s = 1.0`、答错 `s = 0.0`（复习只有"对/错"两态，没有半对）
- 没有挂知识点的题**不做任何掌握度写入**（不猜），复习记录照常成功
- 同一事务：掌握度写失败 → 整个复习失败回滚（宁可 500 也不要状态不一致）

### 4.5 路由

新建 `app/api/v1/mastery.py`（`prefix="/kp/mastery"`，`tags=["mastery"]`），在 `api/v1/__init__.py` 注册。两条路由都 ≤30 行、`Depends(get_current_user)` + 显式 `student` 校验（`require_role("student")`），`Envelope` 组装。

## 5. 前端设计（只改图谱配色）

| 文件 | 改动 |
|---|---|
| `web/src/types/graph.ts` | `GraphSnapshotNode` 加 `mastery: number \| null` |
| `web/src/views/kp/useGraphData.ts` | `nodeColor(mastery: number \| null)`：`null → #9aa4b2`（未评估）/ `<0.4 → #e5484d` / `0.4–0.7 → #f0b429` / `>0.7 → #22c55e`；新增 `masteryLabel()` 供 tooltip |
| `web/src/views/kp/Graph.vue` | 页头文案「颜色=掌握度（灰=未评估）」；tooltip 显示 `掌握度 0.42`；图例旁加三档说明 |
| `web/src/views/kp/useGraphData.spec.ts` | `nodeColor` 用例改按掌握度分档（含 `null`） |
| `web/src/views/kp/Graph.spec.ts` | 快照 fixture 加 `mastery`，断言页头文案 |

`mistake_count` 保留（详情侧栏还在用），不再参与配色。

## 6. 测试

`backend/tests/test_mastery.py`（纯函数 + 用例，FakeSession）：

1. **答对提升**：`M=0, s=1, d=3` → `0.117`；再答对 → `0.220`
2. **答错下降**：`M=0.5, s=0, d=3` → `0.442`；`M=0.05, s=0` → `0.044`（不会变负）
3. **长时间不练衰减**：`M=0.8, S=10, Δt=10 天` → `0.294`；`Δt=0` → `0.8`
4. **连续答对间隔变长**：连对 5 次后 `S=37.8`、`interval=17`；第 1 次答对后 `S=3.6`、`interval=1`（`round(3.6×0.117)=0 → clamp 到 1`）
5. 边界：`M` 上界 1、下界 0；`S` 上界 60、下界 1；`interval` 越界被 clamp
6. `s=0.5` 时 `S` 不变、`correct_cnt` 不增
7. `recompute_user`：乱序事件按时间回放；无 kp 的错题进 `skipped_no_kp`；重复跑结果一致
8. 懒创建：`record_attempts` 前查表 0 行，调用后 1 行；未评估知识点仍 0 行
9. 钩子：`record_review(correct=True)` 后 `attempts+1`、`M` 上升；`correct=False` 后下降；无 kp 的题不建行
10. 接口：未登录 401；他人数据不可见；`GET /kp/mastery` 分页与排序白名单

`backend/tests/test_graph_snapshot.py`：节点带 `mastery`，无行时 `null`。

前端：`useGraphData.spec.ts` 增/改分档用例；`Graph.spec.ts` fixture 与文案。

## 7. 验收口径（真机）

1. `POST /kp/mastery/recompute`（学生 50）：`events_replayed=5`、`rows_built=5`、`skipped_no_kp=31`（该账号 34 条错题，3 条挂知识点共 5 个 KP）；再跑一次结果完全一致（幂等）
2. `GET /kp/mastery`：5 行、`mastery` 全 0、`mastery_t` 全 0、`due_at` 比 `last_practice_at` 晚 1 天（`interval=clamp(round(1×0),1,30)=1`）
3. 用学生 50 对一条 `difficulty=2` 的错题（该账号实际难度只有 1/1/2）`POST /mistakes/{id}/review {"correct": true}`：`GET /kp/mastery` 里对应知识点从 **0 → 0.175**，`attempts+1`、`correct_cnt=1`、`stability=1.80`、`due_at` 比 `last_practice_at` 晚 1 天
4. 再答错一次：`mastery 0.175 → 0.144`、`stability 1.80 → 1.00`
5. 图谱页面：节点颜色按掌握度分档，未评估灰色；tooltip 显示掌握度
6. `scripts/mastery_sim.py`：7 天连续作答表格（每天一条）打印正常；敏感性扫描 3×3 表格输出

## 8. 风险与已知限制

- **参数是工程取值，不是拟合结果**：`K0=0.35 / ×1.8 / ×0.5 / 上限 60` 是"参考 SM-2/FSRS 简化的工程取值"，答辩口径必须这么说；敏感性扫描用来证明"结论不依赖精确参数"。
- 用难度做除数：`difficulty=1` 时一次答对跳 0.35、`difficulty=5` 只跳 0.07，跨度 5 倍；单题影响偏大是方案原意（避免一题定生死），但难度分布不均时（当前 44 条里 34 条是 d=3）会显得"提升慢"，属预期。
- 掌握度只在**错题复习**与**重算**两条路上更新；S5-4 的试卷作答、S5-5 的清单完成都要另接（接口已留成 `record_attempts`）。
- 复习事件只有"对/错"，没有半对；`s=0.5` 目前只会在回放「已订正」状态时出现。
- 接触式遗忘折算依赖 `last_practice_at`；时区一律 UTC，前端展示本地时间（本卡无前端展示）。
- 未做跨用户读取，老师看学生掌握度需要 S4-8 的权限设计。

## 9. 文档同步

- `docs/SCHEMA.md` §6.3：三处口径备注（精度、初始 M=0、懒创建）
- `docs/API.md` §4.6 新增两条 + §4.5 快照加 `mastery`
- `docs/PROGRESS.md`：S4-7 打勾、最近完成、口径
- `docs/DECISIONS.md`：D-050（模型参数来源、挂载点、懒创建、图谱换色、recompute 语义）
- `README.md`：掌握度一段（怎么看、怎么重算）

## 10. 交付物清单

后端：`models/mastery.py`、`alembic/versions/0013_s4_7_mastery.py`、`services/mastery_service.py`、`services/mistake_service.py`（钩子）、`schemas/kp.py`（`MasteryOut`、快照节点加 `mastery`）、`api/v1/mastery.py`、`api/v1/__init__.py`、`scripts/mastery_sim.py`、`tests/test_mastery.py`、`tests/test_graph_snapshot.py`（补字段）。

前端：`types/graph.ts`、`views/kp/useGraphData.ts`、`views/kp/Graph.vue`、两个 spec。

文档：上述 §9 五份 + `.sdd/s4-7/`（evidence / progress / sim 输出）。

## 11. 已确认决策（用户，2026-11-04）

1. **更新触发源**：挂到既有 `POST /mistakes/{id}/review`（答对 s=1、答错 s=0），不改 PATCH 状态入口——手动改状态不等于真答对，避免把掌握度抬成假高。
2. **建行口径**：懒创建，无行 = 未评估；首次作答 M 从 0 起算；不为 108 个知识点灌 0。
3. **recompute 语义**：从错题历史回放重建（待订正 0 / 已订正 0.5 / 已掌握 1），覆盖式重建，幂等。
4. **图谱配色**：本卡就把 S4-6 的「错题数热力」换成掌握度（兑现 D-049），未评估灰色。
5. **读接口**：加 `GET /kp/mastery`（本人，含 M 与 M_t、attempts、due_at），供 S4-8/S5-5 复用。