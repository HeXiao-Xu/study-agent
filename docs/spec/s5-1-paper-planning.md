# S5-1 组卷算法 + 单元测试 — 设计 spec

> 任务卡：`docs/AI协作开发实施计划.md` §S5-1（★关键路径）
> 算法出处：`docs/个性化学习智能体-毕业设计完整方案.md` §6.5（约束满足 + 贪心打分 / 掌握度联动）
> 掌握度出处：`docs/SCHEMA.md` §6.3 + `backend/app/services/mastery_service.py`（S4-7 已交付）
> 日期：2026-11-13

## 1. 背景与目标

S4-1～S4-8 已经有了「题目 ↔ 知识点 ↔ 掌握度」，但**没有任何地方把题拼成一份卷子**。`papers` 表、`/papers/generate`、PDF 导出都只停在契约草稿（`API.md` §8 标着 TODO）。

本卡只做一件事：把方案 §6.5 的组卷算法落成**可脱库单测的纯函数内核**——配额分配 → 候选打分 → 贪心选取 → 约束校验，做到「同输入同种子输出完全一致」且**约束不满足时返回明确原因**。

### 1.1 非目标

- 不建 `papers` / `answers` / `review_items` 表，不加迁移（S5-2 / S5-4 / S5-5）
- 不写 HTTP 接口、不动前端、不改 `API.md` 已定稿条目（S5-2 定稿）
- 不接题库查询（候选由调用方注入，S5-2 从 `questions ⋈ question_kps` 取）
- 不做 PDF、不做 AI 补题（S5-3 / S6-4）
- 不新增依赖、不新增环境变量

## 2. 范围

| 层 | 内容 |
|---|---|
| 服务 | 新增 `backend/app/services/paper_service.py`（纯函数内核 + 数据类） |
| 测试 | 新增 `backend/tests/test_paper.py` |
| 验收 | 临时脚本（不入库）生成 10 份卷子人工检查；证据落 `.sdd/s5-1/` |

只新增这 2 个代码文件。

## 3. 契约决策（本卡定口径，S5-2 沿用）

### 3.1 题目分值：按题型固定分（不改表）

`questions` 表没有分值列，本卡不改表。每题分值取**题型基准分**，默认：

```python
DEFAULT_SCORE_BY_QTYPE = {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
```

可由 `PaperConstraints.score_by_qtype` 整表覆盖（S5-2 从请求透传或配置拼）。**同一题型内所有题同分**，因此：

> **总分 = Σ(题型计数 × 题型基准分)**，本质是题型计数的函数，不是选题结果。

这条决定了后文「总分容差」的做法：不可能靠换题改总分，只能微调题型计数。

### 3.2 总分口径：允许小容差

- 容差 `tolerance = max(1, ceil(total_score_target × score_tolerance_ratio))`，`ratio` 默认 **0.05**
- 首次按题型配比取整得到总分；若 `|score − target| > tolerance`，在**每个题型 ±1 题**（总数不变、各计数 ≥0）的邻域内搜索，取「命中容差且与目标配比的 L1 偏差最小」的解；并列时依次比较 `|score − target|` 更小、再按题型枚举顺序取字典序更小，最多尝试一次邻域（至多 3^k 组合，k ≤ 4，k = 配比里的题型数）
- 邻域无解 → 记 `TOTAL_SCORE_OUT_OF_TOLERANCE` violation，仍用初始计数出卷（`ok=False`），detail 里写「目标 / 实得 / 容差 / 建议（改配比或改分值）」
- 算例（写进单测）：`N=20`、配比 `单选 0.5 / 填空 0.2 / 解答 0.3` → 计数 `10/4/6`、总分 `10×3+4×4+6×8=94`；目标 100、容差 5 → `|94−100|=6` 超差；邻域取「解答 +1、单选 −1」→ `9/4/7`、总分 **99**，命中容差

### 3.3 难度分布：按难度 1–5 权重

`difficulty_dist` 的键是 `1..5`，值是权重（可为 0）。任务卡里的「3:5:2」在 S5-2 的 API 层展开为：

| 档 | 难度 | 权重来源 |
|---|---|---|
| 易 | 1、2 | 0.3 均分 → 各 0.15 |
| 中 | 3 | 0.5 |
| 难 | 4、5 | 0.2 均分 → 各 0.1 |

本卡只认 1–5 的权重表，不实现「3:5:2」解析（那是 S5-2 的入参适配，纯函数保持单一形态）。

### 3.4 掌握度：吃 S4-7 的产物，未评估 = 中性

`mastery_by_kp: Mapping[int, float]` 直接吃 `mastery_service.mastery_values()` 的结果（**已是折算后的 `M_t`**）。无行的知识点 = 未评估，打分为**中性 0.5**，不当作 0 掌握（沿用 D-050 语义）。

一个候选题可能挂多个知识点：候选的掌握度 = 其**约束内**知识点的加权均值（权重取 `question_kps.weight`，缺省 1.0）。

## 4. 算法设计

### 4.1 输入 / 输出数据结构

```python
@dataclass(frozen=True, slots=True)
class PaperConstraints:
    kp_ids: tuple[int, ...]                      # 覆盖清单（顺序即稳定 tie-break 顺序）
    total_questions: int                         # 目标题量 N
    qtype_ratio: Mapping[str, float]             # 题型 -> 权重（>0；键必须是 QuestionType 值）
    difficulty_dist: Mapping[int, float]         # 难度 1..5 -> 权重（>=0，和 >0）
    total_score_target: int
    kp_weights: Mapping[int, float] | None = None        # 覆盖权重，缺省均分
    score_by_qtype: Mapping[str, int] | None = None      # 缺省 DEFAULT_SCORE_BY_QTYPE
    score_tolerance_ratio: float = 0.05
    exclude_recent_days: int = 14
    duration_min: int | None = None
    seed: int = 0

@dataclass(frozen=True, slots=True)
class CandidateQuestion:
    question_id: int
    qtype: str
    difficulty: int
    kp_weights: tuple[tuple[int, float], ...]    # (kp_id, weight)，weight 缺省 1.0
    verified: bool
    origin: str
    last_done_at: datetime | None = None

@dataclass(frozen=True, slots=True)
class ScoreParts:
    difficulty_match: float
    mastery_match: float
    novelty: float
    quality: float
    total: float

@dataclass(frozen=True, slots=True)
class PaperItem:
    question_id: int
    qtype: str
    difficulty: int
    score: int
    kp_ids: tuple[int, ...]
    parts: ScoreParts

@dataclass(frozen=True, slots=True)
class QuotaPlan:
    quota_by_qtype: dict[str, int]         # 最终题型计数（含 3.2 邻域调整）
    quota_by_difficulty: dict[int, int]    # 原始难度配额（借位前）
    quota_by_kp: dict[int, int]            # 原始 kp 配额（借位前）
    target_by_difficulty: dict[int, int]   # 借位后的贪心目标
    target_by_kp: dict[int, int]
    planned_total_score: int               # 按最终题型计数算出的总分
    score_out_of_tolerance: bool           # 3.2 邻域搜索是否无解
    tolerance: int
    warnings: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class Violation:
    code: str          # 见 4.6
    message: str       # 给人看的一句话
    detail: dict[str, object]

@dataclass(frozen=True, slots=True)
class PaperPlan:
    ok: bool
    items: tuple[PaperItem, ...]
    total_score: int
    target_score: int
    quota_by_qtype: dict[str, int]         # 最终题型计数（含 3.2 邻域调整）
    quota_by_difficulty: dict[int, int]    # 原始难度配额（借位前）
    quota_by_kp: dict[int, int]            # 原始 kp 配额（借位前）
    counts_by_qtype: dict[str, int]        # 实选
    counts_by_difficulty: dict[int, int]
    counts_by_kp: dict[int, int]
    violations: tuple[Violation, ...]
    warnings: tuple[str, ...]
    seed: int
```

### 4.2 参数校验（结构性错误直接抛）

`PaperPlanError(Exception)`（S5-2 映射 422/42200）。以下情况抛错，不返回 plan：

- `total_questions < 1`
- `kp_ids` 为空 / 含重复
- `qtype_ratio` 为空、含未知题型、含 ≤0 权重、权重和 ≤0
- `difficulty_dist` 为空、含 1–5 之外的键、含负权重、权重和 ≤0
- `score_by_qtype` 缺任一题型、含 ≤0 分值
- `score_tolerance_ratio < 0`、`exclude_recent_days < 0`、`total_score_target < 1`
- `kp_weights` 含不在 `kp_ids` 里的键，或值 ≤0；缺键的知识点按 1.0
- `now` 是 naive datetime（必须带 tzinfo）；`CandidateQuestion.last_done_at` 允许 naive，统一按 UTC 解释
- 候选本身不合法：`qtype` 不在 `QTYPE_ORDER`、`difficulty` 不在 1–5、`question_id` 重复（同一题重复传入按**首条**处理，不抛错）

**数据不足（题库没那么多题）不算结构错误**，返回 `ok=False` + violation。

### 4.3 配额分配

1. **题型计数**：`largest_remainder(qtype_ratio, N)`；再跑 3.2 的总分邻域搜索。
2. **难度计数**：`largest_remainder(difficulty_dist, N)`。
3. **kp 配额**：`largest_remainder(kp_weights, N)`（`kp_weights` 缺省每个 kp 1.0）。

`largest_remainder(weights, total)` 为公开纯函数：按 `w/Σw × total` 取整、余数按小数部分降序补，小数部分并列时按**入参顺序**（`kp_ids` 顺序 / 枚举顺序）稳定补位；断言 `Σ = total`。

**配额分两份，语义不要混**：

- `alloc` = **原始配额**，只用于报告与 violation 判定（见 4.6）
- `target` = **贪心用目标**，初始化等于 `alloc`，只做缺口借位

**借位规则**：某 kp 的可用候选数 < `target[kp]` 时，缺口按「其他 kp 的富余容量」（`可用候选数 − target` 的正值部分）**从大到小逐个借 1 题**（同容量按 `kp_ids` 顺序），只改 `target`，不改 `alloc`；难度档同理，但缺口**优先借给 |d−d′| 最小的相邻难度**（同距离按富余容量从大到小、再按难度升序）。借位**不改变总题量**（借不出去就保留缺口），也不在这里记 violation——缺口最终由 4.6 用 `alloc` 比对自动报出。

### 4.4 候选打分（四项加权，权重可配）

```python
WEIGHTS = ScoringWeights(difficulty=0.35, mastery=0.30, novelty=0.20, quality=0.15)
```

| 分量 | 公式 | 说明 |
|---|---|---|
| 难度匹配 | `1 − |d − target| / 4`，`target = difficulty_target(M)` | 目标难度：`M < 0.5 → 2`、`0.5 ≤ M ≤ 0.8 → 3`、`M > 0.8 → 5`（方案 6.5 掌握度联动）；`M` 为 `None` 时按 3 |
| 掌握度匹配 | `1 − M_eff`（`M_eff` 缺省 0.5） | 越薄弱越优先，显式把「补基础」写进目标函数 |
| 新颖度 | 没做过 → 1.0；做过 → `clamp(days_since / 30, 0, 1)` | `days_since` 单位天；**`exclude_recent_days` 内的题已被硬排除**，所以实际落在 `[14/30, 1]` |
| 质量 | `verified` 且 `origin ∈ {textbook, exam}` → 1.0；`verified` 其他 → 0.7；未验证 `origin = ai` → 0.4；未验证其他 → 0.5 | 题库可信度分档 |

`total = 0.35·难度 + 0.30·掌握度 + 0.20·新颖度 + 0.15·质量`，四分量与总分都四舍五入到 6 位小数（避免浮点比较打架）。

### 4.5 贪心选取

```
used = set()
remaining = {qtype: quota_by_qtype, difficulty: target_diff, kp: target_kp}
rng = random.Random(seed)
order = 候选（已过滤：涉及约束 kp、且未被近期排除）按 (question_id) 排序后 rng.shuffle
for _ in range(N):
    feasible = [c for c in order if c.id not in used
                and remaining_qtype[c.qtype] > 0 and remaining_diff[c.difficulty] > 0]
    if not feasible: break
    advancing = [c for c in feasible if any(remaining_kp[k] > 0 for k in c.kps ∩ kp_ids)]
    pool = advancing or feasible              # 优先推进 kp 覆盖；配额全满时才允许「同分补位」
    best = max(pool, key=(score, -shuffle 下标))   # 先比分数，同分取洗牌后更靠前者
    选中：used.add, 扣减 qtype/difficulty/该题全部约束 kp（floor 0）
```

- 只按 `question_id` 排序后洗牌，保证**同种子 + 同候选集合 → 同结果**，且候选输入顺序不影响结果
- 同一 `question_id` 绝不重复选（候选里重复传也只算一次）
- 断点保留 `remaining`，供 4.6 生成精确 violation

### 4.6 输出校验与 violation

选取结束后按 `target` 剩余与**原始配额 `alloc`** 汇总：

| code | 触发条件 | detail |
|---|---|---|
| `NO_CANDIDATES` | 过滤后候选池为空 | `{available: 0, excluded_recent: n}`，此时 items 为空、直接返回 |
| `KP_SHORTAGE` | `counts_by_kp[kp] < alloc[kp]` | `{kp_id, need: alloc[kp], selected: 实选, available: 该 kp 可用候选数}` |
| `QTYPE_SHORTAGE` | `counts_by_qtype[q] < alloc_qtype[q]` | `{qtype, need, selected, available}` |
| `DIFFICULTY_SHORTAGE` | `counts_by_difficulty[d] < alloc_diff[d]` | `{difficulty, need, selected, available}` |
| `TOTAL_SCORE_OUT_OF_TOLERANCE` | 3.2 邻域搜索无解 | `{target, achieved, tolerance, suggestion}`（`achieved` = `planned_total_score`） |

- 三类 shortage 用同一套判定（实选 < 原始配额），不重复报；`available` 一律指**过滤后（含近期排除）**涉及该键的候选数
- `ok = not violations`；`warnings` 只放「不构成约束不满足」的说明，本卡只有一条规则：某题型配比权重 > 0 但取整后分配 0 题 → `"题型「单选」按配比取整为 0 题"`；无 warning 时为 `()`
- `counts_by_qtype` / `counts_by_difficulty` / `counts_by_kp` 是**实选统计**，但恒包含约束里的键并补 0（`qtype_ratio` 的键、`difficulty_dist` 的键、`kp_ids`），前端可直接画表；`NO_CANDIDATES` 时全为 0

**题目排序**（输出稳定）：题型按 `单选 → 多选 → 填空 → 解答`（枚举顺序），组内按 `difficulty` 升序，再按「候选在 `kp_ids` 中的最早位置」（多 kp 取最小下标），最后 `question_id` 升序。

### 4.7 公开函数清单

```python
QTYPE_ORDER = ("单选", "多选", "填空", "解答")          # 与 QuestionType 顺序一致
DEFAULT_SCORE_BY_QTYPE = {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
NEUTRAL_MASTERY = 0.5
NOVELTY_WINDOW_DAYS = 30
MASTERY_LOW, MASTERY_HIGH = 0.5, 0.8
TARGET_DIFFICULTY = {low: 2, middle: 3, high: 5}
SCORING_WEIGHTS = ScoringWeights()

def prepare_pool(constraints, candidates, *, now) -> tuple[tuple[CandidateQuestion, ...], int]
    # 去重（同 id 取首条）、校验题型/难度、过滤与约束 kp 无交集者、排除近期做过的
    # 返回 (pool, excluded_recent)

def largest_remainder(weights: Mapping[K, float], total: int) -> dict[K, int]

def allocate_quotas(constraints, pool) -> QuotaPlan
    # 题型/难度/kp 配额 + 总分邻域调整 + 缺口借位（只改 target_*）

def difficulty_target(mastery: float | None) -> int
def novelty_score(last_done_at: datetime | None, *, now: datetime) -> float
def quality_score(*, verified: bool, origin: str) -> float
def score_parts(*, candidate, constraints, mastery_by_kp, now) -> ScoreParts
def select_items(constraints, pool, quotas, *, mastery_by_kp, now) -> tuple[PaperItem, ...]
    # 贪心选取 + 输出排序（题量可能 < total_questions）

def plan_paper(constraints, candidates, *, mastery_by_kp=None, now=None) -> PaperPlan
    # 校验 → prepare_pool → allocate_quotas → select_items → 汇总 counts/violations/warnings
```

`now` 缺省 `datetime.now(timezone.utc)`；`now` 参与新颖度与近期排除，测试必须显式传入，保证可复现。

分层约定：`prepare_pool` / `allocate_quotas` / `select_items` / `score_parts` 是**公开的中间层**（S5-2 预览页与单测都要单独用），`plan_paper` 只是把它们串起来；任何一层都不查库、不写库。

## 5. 测试设计（`backend/tests/test_paper.py`）

纯函数，全部脱库、无网络、无 `Mock` 数据库。

| # | 用例 | 断言要点 |
|---|---|---|
| 1 | `largest_remainder` | Σ = total；精确：`{a:1,b:1}, N=4 → 2/2`；小数并列按入参顺序补；全 0 权重抛错 |
| 2 | `difficulty_target` | `0.2→2`、`0.5→3`、`0.8→3`、`0.81→5`、`None→3`；越界 `M` 不炸 |
| 3 | `novelty_score` | `None→1.0`；14 天 ≈ 0.4667；30 天→1.0；60 天→1.0（clamp） |
| 4 | `quality_score` | 四种组合恰好落在 1.0 / 0.7 / 0.5 / 0.4 |
| 5 | `score_parts` | 加权和 = `total`；改掌握度只动 `mastery_match` 与 `difficulty_match` |
| 6 | **场景①题量不足** | 某 kp 配额 8、可用 2 → `ok=False` + `KP_SHORTAGE`，detail `need=8/selected=2/available=2`；卷子仍按可用题产出 |
| 7 | **场景②难度分布无法满足** | 配比要 5 道 d=5、题库无 d=5 → `DIFFICULTY_SHORTAGE`（`need=5/selected=0/available=0`）；借位后题量仍 = N 且相邻难度补位 |
| 8 | **场景③近期做过的题被排除** | 全部落在 14 天内 → `NO_CANDIDATES` + `excluded_recent` 准确；混合池只选窗口外的题 |
| 9 | 空候选 / 无关候选 | 空池 `NO_CANDIDATES`、items 空；候选 kp 与约束无交集时同样视为空池 |
| 10 | 参数非法 | §4.2 每一类逐条 `pytest.raises(PaperPlanError)`，消息含字段名 |
| 11 | 掌握度联动 | 同 kp 同题型「d=2 vs d=5」二选一：`M=0.2 → 选 d=2`、`M=0.9 → 选 d=5` |
| 12 | 种子复现 | 同 seed 跑两次 plan 完全相等（含 items 顺序）；候选输入顺序打乱后同 seed 结果不变 |
| 13 | 总分容差 | 容差内 → `ok=True`；按 3.2 算例验证邻域修正后 `total=99`；无解 → violation 且 ok=False |
| 14 | 配额取整与补 0 | 题型 / 难度 / kp 三处配额和都 = N；`counts_by_*` 恒含约束键并补 0 |
| 15 | 排序稳定 | 单选→多选→填空→解答，组内难度升序，同难度按 kp 顺序、再 id |
| 16 | 去重 | 候选重复传同一 `question_id`，结果里只出现一次 |
| 17 | 掌握度缺省 | 无 `mastery_by_kp` 记录 → 视为 0.5（断言 `mastery_match = 0.5`） |
| 18 | warning 规则 | 配比 `单选:0.01` 且 N=10 → 计数 0 且 `warnings` 含「题型「单选」按配比取整为 0 题」，但 `ok` 仍为 True |

## 6. 验收口径

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/test_paper.py -q` 全绿
2. `cd backend && .venv/Scripts/python.exe -m pytest -q` 全量不回退（S4-8 基线 **1201 passed**）
3. **10 份卷子人工检查**（临时脚本，不进仓库）：
   - 主数据源：**真实题库**（2026-11-13 实测：56 题 = 单选 8 / 填空 4 / 解答 44；难度 1:5、2:13、3:36、4:2、**无 5**；38 题挂 28 个知识点，另有 18 题无知识点）
   - 约束组合覆盖：20 题标准卷、10 题小卷、单 kp 卷、**难度含 d=5（必然不可满足，验 `DIFFICULTY_SHORTAGE`）**、**题型含多选（题库 0 道，验 `QTYPE_SHORTAGE`）**、近期全做过（空卷）、题型配比极端（解答占 80%）
   - 逐卷检查：题量、题型/难度计数、总分是否在容差、kp 覆盖是否合理、排序是否像真卷、violation 文案是否说人话
   - 输出与结论写 `.sdd/s5-1/acceptance-evidence.md`，**如实标注数据来源**（真实库一轮 / 构造数据一轮分开写）
4. 未覆盖就写「未覆盖」，不允许用「应该没问题」代替

## 7. 风险与已知限制

- **分值不真实**：题型固定分（3/4/4/8）是工程取值，与真实卷面（选择题 5 分、解答 12 分）不一致；S5-2 若要在前端可配，需把 `score_by_qtype` 透传到请求或配置。
- **总分=计数的函数**：换题不可能改总分，只能改题型计数；因此「总分达标」与「题型配比」天然会冲突，冲突时报原因而不是硬凑。
- **贪心不是最优解**：约束多时可能选不到可行解（局部最优）；这是方案 §6.5 的原设计（可解释、可手推、可写论文），不换成黑盒求解器。
- **难度目标只有 3 档**（2/3/5）：`M=0.5–0.8` 全部指向难度 3，与真实题库难度集中 1–3（S4-1 实测）叠加，可能显得难度分布单调；属数据形态问题，S5-2 再接真实难度校准。
- **掌握度是「当前折算值」**：组卷用 `now` 时刻的 `M_t`，同一份约束跨天组卷结果可能不同——这是特性（遗忘驱动），论文里要说明。
- **不校验候选题型/难度合法性**：`CandidateQuestion` 只校验值域（题型属于四种、难度 1–5，见 §4.2），不做业务一致性校验（如「是否同属一个学科」「kp 是否存在」）；S5-2 负责。
- **kp 覆盖与题库结构强相关**：S4-1 已知 43 道解答题里 34 道没挂知识点、复合题只挂 1–2 条；实际组卷能覆盖的 kp 会少于清单，`KP_SHORTAGE` 会常见，属数据现状不是算法缺陷。

## 8. 文档同步（S5-1 落地时）

- `docs/PROGRESS.md`：S5-1 打勾 + 关键口径 + 验收证据
- `docs/DECISIONS.md`：新增一条（D-058 候选）记「题型固定分 / 总分容差 / 难度 1–5 权重表 / 未评估=0.5 / 贪心+种子」
- `docs/API.md`：本卡不改；S5-2 定稿时按本 spec §3 的形态补 `papers/generate` 入参
- `docs/SCHEMA.md`：不改（不建表）
- `AGENTS.md` §9.6：新增「组卷样例」锚点（S5-2 接库后再补完整链路）

## 9. 交付物清单

后端：`backend/app/services/paper_service.py`、`backend/tests/test_paper.py`。

证据：`.sdd/s5-1/acceptance-evidence.md` + 10 份卷子的输出原文。

## 10. 已确认决策（用户，2026-11-13）

1. **本卡只做 S5-1**（组卷算法 + 单测），不连带 S5-2 的建表与接口。
2. **每题分值按题型固定分**（可配，默认 单选 3 / 多选 4 / 填空 4 / 解答 8），不改 `questions` 表、不加迁移。
3. **总分允许小容差**（默认 ±5%，至少 ±1 题分），超差必须返回明确原因，不静默放过。