# S5-1 组卷算法 + 单元测试 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付方案 §6.5 的自适应组卷内核——配额分配、四维打分、贪心选取、约束校验，全部是纯函数、可脱库单测、同种子可复现，且约束不满足时返回明确原因。

**Architecture:** 单文件分层：`prepare_pool`（过滤/去重/近期排除）→ `allocate_quotas`（题型/难度/kp 配额 + 总分邻域 + 缺口借位）→ `score_parts`（难度/掌握度/新颖度/质量四项加权）→ `select_items`（贪心 + 输出排序）→ `plan_paper`（组装 counts/violations）。数据库取候选、落 `papers` 表、HTTP 接口都不在本卡（S5-2）。

**Tech Stack:** Python 3.11；只用标准库（`dataclasses` / `random` / `math` / `itertools`），无新依赖；pytest。

**Spec:** `docs/spec/s5-1-paper-planning.md`

## Global Constraints

- 只新增两个文件：`backend/app/services/paper_service.py`、`backend/tests/test_paper.py`。不改其他任何文件（文档同步步骤除外）。
- 后端命令在 `study-agent/backend` 下执行，解释器 `../.venv/Scripts/python.exe`（2026-11-13 实测可用）。
- 纯函数：**不查库、不写库、不调 LLM、无网络**；所有时间必须 UTC，`now` 必须显式带时区（naive 抛 `PaperPlanError`）。
- 参数是工程取值，不是拟合结果：分值 `{"单选":3,"多选":4,"填空":4,"解答":8}`、权重 `0.35/0.30/0.20/0.15`、难度档 `2/3/5`、容差 `max(1, ceil(target×0.05))`。
- 约束不足（题库没题）→ `ok=False` + violation，不抛异常；结构非法（入参/候选值域）→ 抛 `PaperPlanError`。
- 三类 shortage 统一按「实选 < **原始配额** `alloc`」判定；借位只改贪心目标 `target_*`。
- 同种子 + 同候选集合 → 输出完全一致；候选输入顺序不影响结果。
- 注释只解释「为什么」，不复述「做什么」；函数全部带类型标注。
- 不加依赖、不加环境变量、不加迁移；提交信息 `feat(s5-1): ...` / `docs(s5-1): ...`；**不要 push**。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/services/paper_service.py` | 组卷内核：常量、异常、6 个数据类、7 个公开函数 + 4 个私有辅助 |
| `backend/tests/test_paper.py` | 18 组纯函数用例（含任务卡要求的三场景） |

模块内函数依赖顺序（自上而下）：常量 → `PaperPlanError` → 数据类 → `_as_utc` / `_require_aware` → `prepare_pool` → `largest_remainder` → `_score_tolerance` / `_qtype_total` / `_adjust_qtype_counts` / 三个 `_count_by_*` / `_borrow_difficulty` / `_borrow_kp` → `allocate_quotas` → `difficulty_target` / `novelty_score` / `quality_score` / `_candidate_mastery` / `score_parts` → `select_items` → `plan_paper`。

---

### Task 1: 模块骨架 + 参数校验 + 候选池准备

**Files:**
- Create: `backend/app/services/paper_service.py`
- Create: `backend/tests/test_paper.py`

**Interfaces:**
- Produces（后续任务与 S5-2 依赖）：
  - 常量：`QTYPE_ORDER`、`DEFAULT_SCORE_BY_QTYPE`、`NEUTRAL_MASTERY`、`NOVELTY_WINDOW_DAYS`、`MASTERY_LOW` / `MASTERY_HIGH`、`DIFFICULTY_MIN` / `DIFFICULTY_MAX`、`TRUSTED_ORIGINS`、`SCORING_WEIGHTS`
  - 异常：`PaperPlanError`
  - 数据类：`ScoringWeights`、`PaperConstraints`（含 `score_map` / `kp_weight_map` 属性）、`CandidateQuestion`、`ScoreParts`、`PaperItem`、`QuotaPlan`、`Violation`、`PaperPlan`
  - 函数：`prepare_pool(constraints, candidates, *, now) -> tuple[tuple[CandidateQuestion, ...], int]`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_paper.py`：

```python
"""S5-1 组卷内核单测：纯函数、无数据库、无网络。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.paper_service import (
    DEFAULT_SCORE_BY_QTYPE,
    CandidateQuestion,
    PaperConstraints,
    PaperPlanError,
    prepare_pool,
)

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
KP_A, KP_B = 101, 102


def cand(
    qid: int,
    *,
    qtype: str = "解答",
    difficulty: int = 3,
    kps: list[tuple[int, float]] | None = None,
    verified: bool = True,
    origin: str = "exam",
    last_done_at: datetime | None = None,
) -> CandidateQuestion:
    return CandidateQuestion(
        question_id=qid,
        qtype=qtype,
        difficulty=difficulty,
        kp_weights=tuple(kps if kps is not None else [(KP_A, 1.0)]),
        verified=verified,
        origin=origin,
        last_done_at=last_done_at,
    )


def make_constraints(**overrides) -> PaperConstraints:
    params = dict(
        kp_ids=(KP_A,),
        total_questions=10,
        qtype_ratio={"解答": 1.0},
        difficulty_dist={3: 1.0},
        total_score_target=80,
        seed=7,
    )
    params.update(overrides)
    return PaperConstraints(**params)


def many(count: int, *, start: int = 1, **kwargs) -> list[CandidateQuestion]:
    return [cand(start + index, **kwargs) for index in range(count)]


def mixed_pool() -> list[CandidateQuestion]:
    """12 单选 + 6 填空 + 9 解答，全部 d=3、同挂 KP_A（够 20 题配额）。"""
    pool: list[CandidateQuestion] = []
    next_id = 1
    for qtype, count in (("单选", 12), ("填空", 6), ("解答", 9)):
        for _ in range(count):
            pool.append(cand(next_id, qtype=qtype, difficulty=3))
            next_id += 1
    return pool


def test_constraints_expose_default_score_map_and_kp_weights() -> None:
    constraints = make_constraints()
    assert constraints.score_map == DEFAULT_SCORE_BY_QTYPE
    assert constraints.kp_weight_map == {KP_A: 1.0}


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"total_questions": 0}, "total_questions"),
        ({"kp_ids": ()}, "kp_ids"),
        ({"kp_ids": (KP_A, KP_A)}, "kp_ids"),
        ({"qtype_ratio": {}}, "qtype_ratio"),
        ({"qtype_ratio": {"判断题": 1.0}}, "qtype_ratio"),
        ({"qtype_ratio": {"单选": 0.0}}, "qtype_ratio"),
        ({"difficulty_dist": {}}, "difficulty_dist"),
        ({"difficulty_dist": {6: 1.0}}, "difficulty_dist"),
        ({"difficulty_dist": {3: -1.0}}, "difficulty_dist"),
        ({"score_by_qtype": {"单选": 3, "填空": 4, "解答": 8}}, "score_by_qtype"),
        ({"score_by_qtype": {"单选": 3, "多选": 4, "填空": 4, "解答": 0}}, "score_by_qtype"),
        ({"score_tolerance_ratio": -0.1}, "score_tolerance_ratio"),
        ({"exclude_recent_days": -1}, "exclude_recent_days"),
        ({"total_score_target": 0}, "total_score_target"),
        ({"kp_weights": {999: 1.0}}, "kp_weights"),
        ({"kp_weights": {KP_A: 0.0}}, "kp_weights"),
    ],
)
def test_constraints_reject_invalid_input(overrides, message) -> None:
    with pytest.raises(PaperPlanError, match=message):
        make_constraints(**overrides)


def test_prepare_pool_dedupes_and_keeps_first() -> None:
    constraints = make_constraints(difficulty_dist={2: 1.0})
    pool, excluded = prepare_pool(
        constraints,
        [cand(1, difficulty=2), cand(1, difficulty=3), cand(2, difficulty=2)],
        now=NOW,
    )
    assert [item.question_id for item in pool] == [1, 2]
    assert pool[0].difficulty == 2
    assert excluded == 0


def test_prepare_pool_drops_candidates_without_constrained_kp() -> None:
    constraints = make_constraints(kp_ids=(KP_A,))
    pool, _ = prepare_pool(
        constraints,
        [cand(1, kps=[(KP_B, 1.0)]), cand(2, kps=[(KP_A, 0.8), (KP_B, 0.5)])],
        now=NOW,
    )
    assert [item.question_id for item in pool] == [2]
    assert pool[0].kp_weights == ((KP_A, 0.8),)


def test_prepare_pool_excludes_recent_and_keeps_old() -> None:
    constraints = make_constraints()
    candidates = many(7, start=1, last_done_at=NOW - timedelta(days=20)) + many(
        3, start=101, last_done_at=NOW - timedelta(days=3)
    )
    pool, excluded = prepare_pool(constraints, candidates, now=NOW)
    assert [item.question_id for item in pool] == list(range(1, 8))
    assert excluded == 3


def test_candidate_with_unknown_qtype_raises() -> None:
    with pytest.raises(PaperPlanError, match="题型"):
        prepare_pool(make_constraints(), [cand(1, qtype="判断题")], now=NOW)


def test_candidate_with_invalid_difficulty_raises() -> None:
    with pytest.raises(PaperPlanError, match="难度"):
        prepare_pool(make_constraints(), [cand(1, difficulty=6)], now=NOW)


def test_prepare_pool_rejects_naive_now() -> None:
    with pytest.raises(PaperPlanError, match="now"):
        prepare_pool(make_constraints(), [cand(1)], now=datetime(2026, 11, 13, 9, 0))


def test_prepare_pool_treats_naive_last_done_at_as_utc() -> None:
    constraints = make_constraints()
    naive = (NOW - timedelta(days=3)).replace(tzinfo=None)
    pool, excluded = prepare_pool(constraints, [cand(1, last_done_at=naive)], now=NOW)
    assert pool == ()
    assert excluded == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.paper_service'`

- [ ] **Step 3: 写最小实现**

创建 `backend/app/services/paper_service.py`：

```python
"""S5-1 自适应组卷内核（方案 §6.5）：纯函数、可脱库单测、同种子可复现。

候选题库与掌握度由调用方注入；落 papers 表与 HTTP 接口在 S5-2，PDF 在 S5-3。
参数是工程取值，不是拟合结果——答辩口径见 docs/spec/s5-1-paper-planning.md §7。
"""
from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TypeVar

QTYPE_ORDER: tuple[str, ...] = ("单选", "多选", "填空", "解答")
"""题型顺序同时决定配额取整的稳定补位与试卷输出顺序（与 QuestionType 一致）。"""

DEFAULT_SCORE_BY_QTYPE: Mapping[str, int] = {"单选": 3, "多选": 4, "填空": 4, "解答": 8}
"""questions 表没有分值列：同一题型同分，总分因此是题型计数的函数（spec §3.1）。"""

NEUTRAL_MASTERY = 0.5
"""无 masteries 行 = 未评估；打分为中性，不当作 0 掌握（D-050）。"""

NOVELTY_WINDOW_DAYS = 30.0
MASTERY_LOW = 0.5
MASTERY_HIGH = 0.8
TARGET_DIFFICULTY_LOW = 2
TARGET_DIFFICULTY_MIDDLE = 3
TARGET_DIFFICULTY_HIGH = 5
DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 5
DEFAULT_SCORE_TOLERANCE_RATIO = 0.05
DEFAULT_EXCLUDE_RECENT_DAYS = 14
TRUSTED_ORIGINS = frozenset({"textbook", "exam"})
SCORE_PRECISION = 6

K = TypeVar("K")


class PaperPlanError(Exception):
    """组卷入参不合法（S5-2 映射 422/42200）；题库不足不抛这个，走 violation。"""


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    difficulty: float = 0.35
    mastery: float = 0.30
    novelty: float = 0.20
    quality: float = 0.15


SCORING_WEIGHTS = ScoringWeights()


@dataclass(frozen=True, slots=True)
class PaperConstraints:
    kp_ids: tuple[int, ...]
    total_questions: int
    qtype_ratio: Mapping[str, float]
    difficulty_dist: Mapping[int, float]
    total_score_target: int
    kp_weights: Mapping[int, float] | None = None
    score_by_qtype: Mapping[str, int] | None = None
    score_tolerance_ratio: float = DEFAULT_SCORE_TOLERANCE_RATIO
    exclude_recent_days: int = DEFAULT_EXCLUDE_RECENT_DAYS
    duration_min: int | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        if self.total_questions < 1:
            raise PaperPlanError("total_questions 必须 ≥ 1")
        if not self.kp_ids:
            raise PaperPlanError("kp_ids 不能为空")
        if len(set(self.kp_ids)) != len(self.kp_ids):
            raise PaperPlanError("kp_ids 不能包含重复知识点")
        if not self.qtype_ratio:
            raise PaperPlanError("qtype_ratio 不能为空")
        unknown_qtype = [qtype for qtype in self.qtype_ratio if qtype not in QTYPE_ORDER]
        if unknown_qtype:
            raise PaperPlanError(f"qtype_ratio 含未知题型：{unknown_qtype}")
        if any(float(weight) <= 0 for weight in self.qtype_ratio.values()):
            raise PaperPlanError("qtype_ratio 的权重必须大于 0")
        if not self.difficulty_dist:
            raise PaperPlanError("difficulty_dist 不能为空")
        unknown_difficulty = [
            difficulty
            for difficulty in self.difficulty_dist
            if difficulty not in range(DIFFICULTY_MIN, DIFFICULTY_MAX + 1)
        ]
        if unknown_difficulty:
            raise PaperPlanError(f"difficulty_dist 含 1–5 之外的难度：{unknown_difficulty}")
        if any(float(weight) < 0 for weight in self.difficulty_dist.values()):
            raise PaperPlanError("difficulty_dist 的权重不能为负")
        if sum(float(weight) for weight in self.difficulty_dist.values()) <= 0:
            raise PaperPlanError("difficulty_dist 的权重之和必须大于 0")
        scores = self.score_by_qtype or DEFAULT_SCORE_BY_QTYPE
        missing_qtype = [qtype for qtype in QTYPE_ORDER if qtype not in scores]
        if missing_qtype:
            raise PaperPlanError(f"score_by_qtype 缺少题型：{missing_qtype}")
        extra_qtype = [qtype for qtype in scores if qtype not in QTYPE_ORDER]
        if extra_qtype:
            raise PaperPlanError(f"score_by_qtype 含未知题型：{extra_qtype}")
        if any(int(score) <= 0 for score in scores.values()):
            raise PaperPlanError("score_by_qtype 的分值必须大于 0")
        if self.total_score_target < 1:
            raise PaperPlanError("total_score_target 必须 ≥ 1")
        if self.score_tolerance_ratio < 0:
            raise PaperPlanError("score_tolerance_ratio 不能为负")
        if self.exclude_recent_days < 0:
            raise PaperPlanError("exclude_recent_days 不能为负")
        if self.kp_weights is not None:
            unknown_kp = [kp_id for kp_id in self.kp_weights if kp_id not in self.kp_ids]
            if unknown_kp:
                raise PaperPlanError(f"kp_weights 含不在 kp_ids 里的知识点：{unknown_kp}")
            if any(float(weight) <= 0 for weight in self.kp_weights.values()):
                raise PaperPlanError("kp_weights 的权重必须大于 0")

    @property
    def score_map(self) -> dict[str, int]:
        return dict(self.score_by_qtype or DEFAULT_SCORE_BY_QTYPE)

    @property
    def kp_weight_map(self) -> dict[int, float]:
        weights = {kp_id: 1.0 for kp_id in self.kp_ids}
        if self.kp_weights:
            weights.update({kp_id: float(weight) for kp_id, weight in self.kp_weights.items()})
        return weights


@dataclass(frozen=True, slots=True)
class CandidateQuestion:
    question_id: int
    qtype: str
    difficulty: int
    kp_weights: tuple[tuple[int, float], ...]
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
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    target_by_difficulty: dict[int, int]
    target_by_kp: dict[int, int]
    planned_total_score: int
    score_out_of_tolerance: bool
    tolerance: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    message: str
    detail: dict[str, object]


@dataclass(frozen=True, slots=True)
class PaperPlan:
    ok: bool
    items: tuple[PaperItem, ...]
    total_score: int
    target_score: int
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    counts_by_qtype: dict[str, int]
    counts_by_difficulty: dict[int, int]
    counts_by_kp: dict[int, int]
    violations: tuple[Violation, ...]
    warnings: tuple[str, ...]
    seed: int


def _as_utc(value: datetime) -> datetime:
    """naive 按 UTC 解释：题库里 last_done_at 可能来自不带时区的字段。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise PaperPlanError(f"{name} 必须带时区（UTC）")


def prepare_pool(
    constraints: PaperConstraints,
    candidates: Sequence[CandidateQuestion],
    *,
    now: datetime,
) -> tuple[tuple[CandidateQuestion, ...], int]:
    """过滤出可选题：同 id 取首条、去掉与约束 kp 无交集者、排除近期做过的题。"""
    _require_aware(now, "now")
    moment = _as_utc(now)
    cutoff = moment - timedelta(days=constraints.exclude_recent_days)
    kp_set = frozenset(constraints.kp_ids)
    pool: list[CandidateQuestion] = []
    seen: set[int] = set()
    excluded_recent = 0
    for candidate in candidates:
        if candidate.question_id in seen:
            continue
        seen.add(candidate.question_id)
        if candidate.qtype not in QTYPE_ORDER:
            raise PaperPlanError(
                f"候选题 {candidate.question_id} 的题型非法：{candidate.qtype}"
            )
        if candidate.difficulty not in range(DIFFICULTY_MIN, DIFFICULTY_MAX + 1):
            raise PaperPlanError(
                f"候选题 {candidate.question_id} 的难度非法：{candidate.difficulty}"
            )
        weights: dict[int, float] = {}
        for kp_id, weight in candidate.kp_weights:
            if kp_id in kp_set and kp_id not in weights:
                weights[kp_id] = float(weight)
        if not weights:
            continue
        if candidate.last_done_at is not None and _as_utc(candidate.last_done_at) >= cutoff:
            excluded_recent += 1
            continue
        pool.append(replace(candidate, kp_weights=tuple(weights.items())))
    return tuple(pool), excluded_recent
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: PASS（7 passed + 16 param 子项）

- [ ] **Step 5: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/paper_service.py backend/tests/test_paper.py
git commit -m "feat(s5-1): 组卷内核骨架、参数校验与候选池准备"
```

---

### Task 2: 配额分配（题型/难度/kp + 总分邻域 + 缺口借位）

**Files:**
- Modify: `backend/app/services/paper_service.py`（在 `prepare_pool` 之后追加）
- Modify: `backend/tests/test_paper.py`（补 import 与用例）

**Interfaces:**
- Consumes: Task 1 的 `PaperConstraints` / `CandidateQuestion` / `QuotaPlan` / `prepare_pool`
- Produces:
  - `largest_remainder(weights: Mapping[K, float], total: int) -> dict[K, int]`
  - `allocate_quotas(constraints, pool) -> QuotaPlan`

- [ ] **Step 1: 写失败测试**

在 `test_paper.py` 的 import 块补上：

```python
from app.services.paper_service import (
    DEFAULT_SCORE_BY_QTYPE,
    CandidateQuestion,
    PaperConstraints,
    PaperPlanError,
    allocate_quotas,
    largest_remainder,
    prepare_pool,
)
```

在文件末尾追加：

```python
def test_largest_remainder_sums_to_total() -> None:
    assert largest_remainder({"a": 1.0, "b": 1.0}, 4) == {"a": 2, "b": 2}
    assert largest_remainder({"单选": 0.5, "填空": 0.2, "解答": 0.3}, 20) == {
        "单选": 10,
        "填空": 4,
        "解答": 6,
    }


def test_largest_remainder_breaks_ties_by_input_order() -> None:
    assert largest_remainder({"a": 1.0, "b": 1.0, "c": 1.0}, 2) == {"a": 1, "b": 1, "c": 0}


def test_largest_remainder_handles_zero_weight() -> None:
    assert largest_remainder({"a": 0.0, "b": 1.0}, 3) == {"a": 0, "b": 3}


@pytest.mark.parametrize("weights", [{}, {"a": 0.0}, {"a": -1.0}])
def test_largest_remainder_rejects_bad_weights(weights) -> None:
    with pytest.raises(PaperPlanError):
        largest_remainder(weights, 3)


def test_allocate_quotas_fills_all_three_dimensions() -> None:
    constraints = make_constraints(
        kp_ids=(KP_A, KP_B),
        total_questions=10,
        qtype_ratio={"单选": 0.4, "填空": 0.2, "解答": 0.4},
        difficulty_dist={2: 0.3, 3: 0.7},
        total_score_target=52,
    )
    quotas = allocate_quotas(constraints, tuple(many(20)))
    assert sum(quotas.quota_by_qtype.values()) == 10
    assert sum(quotas.quota_by_difficulty.values()) == 10
    assert sum(quotas.quota_by_kp.values()) == 10
    assert sum(quotas.target_by_difficulty.values()) == 10
    assert sum(quotas.target_by_kp.values()) == 10
    assert quotas.quota_by_qtype == {"单选": 4, "填空": 2, "解答": 4}
    assert quotas.planned_total_score == 52
    assert quotas.score_out_of_tolerance is False


def test_allocate_quotas_borrows_difficulty_from_neighbour() -> None:
    constraints = make_constraints(
        total_questions=10,
        difficulty_dist={5: 0.5, 3: 0.5},
        total_score_target=80,
    )
    pool = tuple(many(20, difficulty=3))
    quotas = allocate_quotas(constraints, pool)
    assert quotas.quota_by_difficulty == {3: 5, 5: 5}
    assert quotas.target_by_difficulty == {3: 10, 5: 0}


def test_allocate_quotas_borrows_kp_from_spare() -> None:
    constraints = make_constraints(kp_ids=(KP_A, KP_B), total_questions=10, total_score_target=80)
    pool = tuple(
        many(2, start=1, kps=[(KP_A, 1.0)])
        + many(10, start=11, kps=[(KP_B, 1.0)])
    )
    quotas = allocate_quotas(constraints, pool)
    assert quotas.quota_by_kp == {KP_A: 5, KP_B: 5}
    assert quotas.target_by_kp == {KP_A: 2, KP_B: 8}


def test_allocate_quotas_tunes_qtype_counts_to_hit_score() -> None:
    constraints = make_constraints(
        total_questions=20,
        qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
        difficulty_dist={3: 1.0},
        total_score_target=100,
    )
    quotas = allocate_quotas(constraints, tuple(mixed_pool()))
    assert quotas.quota_by_qtype == {"单选": 9, "填空": 4, "解答": 7}
    assert quotas.planned_total_score == 99
    assert quotas.score_out_of_tolerance is False


def test_allocate_quotas_reports_impossible_score() -> None:
    constraints = make_constraints(
        total_questions=20,
        qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
        difficulty_dist={3: 1.0},
        total_score_target=200,
    )
    quotas = allocate_quotas(constraints, tuple(mixed_pool()))
    assert quotas.quota_by_qtype == {"单选": 10, "填空": 4, "解答": 6}
    assert quotas.planned_total_score == 94
    assert quotas.score_out_of_tolerance is True
    assert quotas.tolerance == 10


def test_allocate_quotas_warns_when_qtype_rounds_to_zero() -> None:
    constraints = make_constraints(
        qtype_ratio={"单选": 0.01, "解答": 0.99},
        difficulty_dist={3: 1.0},
        total_score_target=80,
    )
    quotas = allocate_quotas(constraints, tuple(mixed_pool()))
    assert quotas.quota_by_qtype == {"单选": 0, "解答": 10}
    assert quotas.warnings == ("题型「单选」按配比取整为 0 题",)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: FAIL — `ImportError: cannot import name 'allocate_quotas' from 'app.services.paper_service'`

- [ ] **Step 3: 写实现**

在 `prepare_pool` 之后追加：

```python
def largest_remainder(weights: Mapping[K, float], total: int) -> dict[K, int]:
    """最大余数法：先取整、再按小数部分补足；并列时按入参顺序（稳定排序）。"""
    if total < 0:
        raise PaperPlanError("配额总数不能为负")
    if not weights:
        raise PaperPlanError("配额权重不能为空")
    values = {key: float(weight) for key, weight in weights.items()}
    if any(weight < 0 for weight in values.values()):
        raise PaperPlanError("配额权重不能为负")
    weight_sum = sum(values.values())
    if weight_sum <= 0:
        raise PaperPlanError("配额权重之和必须大于 0")
    raw = {key: weight / weight_sum * total for key, weight in values.items()}
    result = {key: int(math.floor(raw[key])) for key in values}
    missing = total - sum(result.values())
    for key in sorted(values, key=lambda key: -(raw[key] - result[key]))[:missing]:
        result[key] += 1
    return result


def _score_tolerance(target: int, ratio: float) -> int:
    return max(1, math.ceil(target * ratio))


def _qtype_total(counts: Mapping[str, int], score_map: Mapping[str, int]) -> int:
    return sum(int(counts[qtype]) * int(score_map[qtype]) for qtype in counts)


def _adjust_qtype_counts(
    constraints: PaperConstraints, counts: Mapping[str, int]
) -> tuple[dict[str, int], int, bool]:
    """总分容差只能靠题型计数微调：题分按题型固定，换题不改总分（spec §3.2）。"""
    score_map = constraints.score_map
    target = constraints.total_score_target
    tolerance = _score_tolerance(target, constraints.score_tolerance_ratio)
    base = _qtype_total(counts, score_map)
    if abs(base - target) <= tolerance:
        return dict(counts), base, False
    keys = [qtype for qtype in QTYPE_ORDER if qtype in counts]
    best_rank: tuple[int, int, tuple[int, ...]] | None = None
    best_counts: dict[str, int] | None = None
    best_score = base
    for deltas in itertools.product((-1, 0, 1), repeat=len(keys)):
        if sum(deltas) != 0:
            continue
        candidate = dict(counts)
        valid = True
        for qtype, delta in zip(keys, deltas):
            candidate[qtype] += delta
            if candidate[qtype] < 0:
                valid = False
                break
        if not valid:
            continue
        achieved = _qtype_total(candidate, score_map)
        if abs(achieved - target) > tolerance:
            continue
        rank = (sum(abs(delta) for delta in deltas), abs(achieved - target), deltas)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_counts = candidate
            best_score = achieved
    if best_counts is None:
        return dict(counts), base, True
    return best_counts, best_score, False


def _count_by_qtype(pool: Sequence[CandidateQuestion]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in pool:
        counts[candidate.qtype] = counts.get(candidate.qtype, 0) + 1
    return counts


def _count_by_difficulty(pool: Sequence[CandidateQuestion]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for candidate in pool:
        counts[candidate.difficulty] = counts.get(candidate.difficulty, 0) + 1
    return counts


def _count_by_kp(pool: Sequence[CandidateQuestion]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for candidate in pool:
        for kp_id, _weight in candidate.kp_weights:
            counts[kp_id] = counts.get(kp_id, 0) + 1
    return counts


def _borrow_difficulty(
    alloc: Mapping[int, int], available: Mapping[int, int]
) -> dict[int, int]:
    """题库某难度不够时，把缺口借给相邻难度（先近距离、再富余多、再难度小）。"""
    target = dict(alloc)
    for difficulty in sorted(alloc):
        deficit = target[difficulty] - available.get(difficulty, 0)
        if deficit <= 0:
            continue
        target[difficulty] -= deficit
        while deficit > 0:
            donors = [
                other
                for other in target
                if other != difficulty and available.get(other, 0) - target[other] > 0
            ]
            if not donors:
                break
            donor = min(
                donors,
                key=lambda other: (
                    abs(other - difficulty),
                    -(available[other] - target[other]),
                    other,
                ),
            )
            target[donor] += 1
            deficit -= 1
    return target


def _borrow_kp(alloc: Mapping[int, int], available: Mapping[int, int]) -> dict[int, int]:
    """某个知识点候选不足时，把缺口借给富余最多的知识点（同富余按 kp 顺序）。"""
    target = dict(alloc)
    for kp_id in alloc:
        deficit = target[kp_id] - available.get(kp_id, 0)
        if deficit <= 0:
            continue
        target[kp_id] -= deficit
        while deficit > 0:
            donors = [
                other
                for other in target
                if other != kp_id and available.get(other, 0) - target[other] > 0
            ]
            if not donors:
                break
            donor = max(
                donors, key=lambda other: (available[other] - target[other], -other)
            )
            target[donor] += 1
            deficit -= 1
    return target


def allocate_quotas(
    constraints: PaperConstraints, pool: Sequence[CandidateQuestion]
) -> QuotaPlan:
    """题型/难度/kp 三份配额 + 总分邻域调整 + 缺口借位；只算不选。"""
    total = constraints.total_questions
    base_counts = largest_remainder(constraints.qtype_ratio, total)
    qtype_counts, planned_score, score_out = _adjust_qtype_counts(constraints, base_counts)
    difficulty_alloc = largest_remainder(constraints.difficulty_dist, total)
    kp_alloc = largest_remainder(constraints.kp_weight_map, total)
    target_by_difficulty = _borrow_difficulty(difficulty_alloc, _count_by_difficulty(pool))
    target_by_kp = _borrow_kp(kp_alloc, _count_by_kp(pool))
    warnings = tuple(
        f"题型「{qtype}」按配比取整为 0 题"
        for qtype in QTYPE_ORDER
        if qtype in constraints.qtype_ratio and qtype_counts.get(qtype, 0) == 0
    )
    return QuotaPlan(
        quota_by_qtype=qtype_counts,
        quota_by_difficulty=difficulty_alloc,
        quota_by_kp=kp_alloc,
        target_by_difficulty=target_by_difficulty,
        target_by_kp=target_by_kp,
        planned_total_score=planned_score,
        score_out_of_tolerance=score_out,
        tolerance=_score_tolerance(
            constraints.total_score_target, constraints.score_tolerance_ratio
        ),
        warnings=warnings,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/paper_service.py backend/tests/test_paper.py
git commit -m "feat(s5-1): 组卷配额分配与总分容差邻域搜索"
```

---

### Task 3: 四维打分的纯函数

**Files:**
- Modify: `backend/app/services/paper_service.py`（在 `allocate_quotas` 之后追加）
- Modify: `backend/tests/test_paper.py`

**Interfaces:**
- Consumes: `PaperConstraints` / `CandidateQuestion` / `ScoreParts` / `SCORING_WEIGHTS`
- Produces:
  - `difficulty_target(mastery: float | None) -> int`
  - `novelty_score(last_done_at: datetime | None, *, now: datetime) -> float`
  - `quality_score(*, verified: bool, origin: str) -> float`
  - `score_parts(*, candidate, constraints, mastery_by_kp, now) -> ScoreParts`

- [ ] **Step 1: 写失败测试**

import 块补 `NEUTRAL_MASTERY, difficulty_target, novelty_score, quality_score, score_parts`，末尾追加：

```python
def test_difficulty_target_follows_mastery_bands() -> None:
    assert difficulty_target(None) == 3
    assert difficulty_target(0.2) == 2
    assert difficulty_target(0.5) == 3
    assert difficulty_target(0.8) == 3
    assert difficulty_target(0.81) == 5
    assert difficulty_target(-0.5) == 2
    assert difficulty_target(1.5) == 5


def test_novelty_score_decays_and_clamps() -> None:
    assert novelty_score(None, now=NOW) == 1.0
    assert novelty_score(NOW - timedelta(days=14), now=NOW) == pytest.approx(0.466667, abs=1e-6)
    assert novelty_score(NOW - timedelta(days=30), now=NOW) == 1.0
    assert novelty_score(NOW - timedelta(days=60), now=NOW) == 1.0
    assert novelty_score(NOW + timedelta(days=2), now=NOW) == 0.0


@pytest.mark.parametrize(
    "verified, origin, expected",
    [
        (True, "exam", 1.0),
        (True, "textbook", 1.0),
        (True, "upload", 0.7),
        (False, "ai", 0.4),
        (False, "upload", 0.5),
    ],
)
def test_quality_score_tiers(verified, origin, expected) -> None:
    assert quality_score(verified=verified, origin=origin) == expected


def test_score_parts_weights_and_components() -> None:
    parts = score_parts(
        candidate=cand(1, difficulty=3),
        constraints=make_constraints(),
        mastery_by_kp={KP_A: 0.4},
        now=NOW,
    )
    assert parts.difficulty_match == pytest.approx(0.75)
    assert parts.mastery_match == pytest.approx(0.6)
    assert parts.novelty == 1.0
    assert parts.quality == 1.0
    assert parts.total == pytest.approx(0.7925)


def test_score_parts_strong_mastery_tolerates_harder_question() -> None:
    parts = score_parts(
        candidate=cand(1, difficulty=3),
        constraints=make_constraints(),
        mastery_by_kp={KP_A: 0.9},
        now=NOW,
    )
    assert parts.difficulty_match == pytest.approx(0.5)
    assert parts.mastery_match == pytest.approx(0.1)
    assert parts.total == pytest.approx(0.555)


def test_score_parts_defaults_to_neutral_mastery() -> None:
    parts = score_parts(
        candidate=cand(1, difficulty=3),
        constraints=make_constraints(),
        mastery_by_kp={},
        now=NOW,
    )
    assert parts.mastery_match == pytest.approx(NEUTRAL_MASTERY)
    assert parts.difficulty_match == pytest.approx(1.0)
    assert parts.total == pytest.approx(0.35 * 1.0 + 0.30 * 0.5 + 0.20 + 0.15)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: FAIL — `ImportError: cannot import name 'difficulty_target'`

- [ ] **Step 3: 写实现**

在 `allocate_quotas` 之后追加：

```python
def difficulty_target(mastery: float | None) -> int:
    """掌握度联动（方案 §6.5）：薄弱配基础题、熟练配难题、未评估走中档。"""
    if mastery is None:
        return TARGET_DIFFICULTY_MIDDLE
    value = min(1.0, max(0.0, float(mastery)))
    if value < MASTERY_LOW:
        return TARGET_DIFFICULTY_LOW
    if value > MASTERY_HIGH:
        return TARGET_DIFFICULTY_HIGH
    return TARGET_DIFFICULTY_MIDDLE


def novelty_score(last_done_at: datetime | None, *, now: datetime) -> float:
    """30 天内做过的时间越近越不新颖；近期窗内的题在 prepare_pool 已被硬排除。"""
    if last_done_at is None:
        return 1.0
    _require_aware(now, "now")
    days = (_as_utc(now) - _as_utc(last_done_at)).total_seconds() / 86400.0
    return round(min(1.0, max(0.0, days / NOVELTY_WINDOW_DAYS)), SCORE_PRECISION)


def quality_score(*, verified: bool, origin: str) -> float:
    """答案可信度分档：真题/课本 > 其他已核对 > 未核对 > AI 未核对。"""
    if verified:
        return 1.0 if origin in TRUSTED_ORIGINS else 0.7
    return 0.4 if origin == "ai" else 0.5


def _candidate_mastery(
    candidate: CandidateQuestion, mastery_by_kp: Mapping[int, float]
) -> float:
    weighted = 0.0
    weight_sum = 0.0
    for kp_id, weight in candidate.kp_weights:
        value = max(0.0, float(weight))
        weighted += value * float(mastery_by_kp.get(kp_id, NEUTRAL_MASTERY))
        weight_sum += value
    if weight_sum <= 0:
        return NEUTRAL_MASTERY
    return min(1.0, max(0.0, weighted / weight_sum))


def score_parts(
    *,
    candidate: CandidateQuestion,
    constraints: PaperConstraints,
    mastery_by_kp: Mapping[int, float],
    now: datetime,
) -> ScoreParts:
    """四项加权：难度匹配 + 掌握度匹配 + 新颖度 + 质量（spec §4.4）。"""
    mastery = _candidate_mastery(candidate, mastery_by_kp)
    difficulty_match = round(
        1.0
        - abs(candidate.difficulty - difficulty_target(mastery))
        / (DIFFICULTY_MAX - DIFFICULTY_MIN),
        SCORE_PRECISION,
    )
    mastery_match = round(1.0 - mastery, SCORE_PRECISION)
    novelty = novelty_score(candidate.last_done_at, now=now)
    quality = quality_score(verified=candidate.verified, origin=candidate.origin)
    total = round(
        SCORING_WEIGHTS.difficulty * difficulty_match
        + SCORING_WEIGHTS.mastery * mastery_match
        + SCORING_WEIGHTS.novelty * novelty
        + SCORING_WEIGHTS.quality * quality,
        SCORE_PRECISION,
    )
    return ScoreParts(
        difficulty_match=difficulty_match,
        mastery_match=mastery_match,
        novelty=novelty,
        quality=quality,
        total=total,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/paper_service.py backend/tests/test_paper.py
git commit -m "feat(s5-1): 组卷打分四项（难度/掌握度/新颖度/质量）"
```

---

### Task 4: 贪心选取 + 输出排序

**Files:**
- Modify: `backend/app/services/paper_service.py`（在 `score_parts` 之后追加）
- Modify: `backend/tests/test_paper.py`

**Interfaces:**
- Consumes: `PaperConstraints` / `QuotaPlan` / `score_parts` / `QTYPE_ORDER`
- Produces: `select_items(constraints, pool, quotas, *, mastery_by_kp, now) -> tuple[PaperItem, ...]`

- [ ] **Step 1: 写失败测试**

import 块补：

```python
from app.services.paper_service import (
    DEFAULT_SCORE_BY_QTYPE,
    NEUTRAL_MASTERY,
    QTYPE_ORDER,
    CandidateQuestion,
    PaperConstraints,
    PaperItem,
    PaperPlanError,
    allocate_quotas,
    difficulty_target,
    largest_remainder,
    novelty_score,
    prepare_pool,
    quality_score,
    score_parts,
    select_items,
)
```

末尾追加：

```python
def test_select_items_fills_all_quotas() -> None:
    constraints = make_constraints(
        total_questions=6,
        qtype_ratio={"单选": 0.5, "解答": 0.5},
        difficulty_dist={2: 0.5, 3: 0.5},
        total_score_target=33,
    )
    pool = tuple(
        many(3, start=1, qtype="单选", difficulty=2)
        + many(3, start=4, qtype="单选", difficulty=3)
        + many(3, start=7, qtype="解答", difficulty=2)
        + many(3, start=10, qtype="解答", difficulty=3)
    )
    quotas = allocate_quotas(constraints, pool)
    items = select_items(constraints, pool, quotas, mastery_by_kp={}, now=NOW)
    assert len(items) == 6
    assert sum(1 for item in items if item.qtype == "单选") == 3
    assert sum(1 for item in items if item.qtype == "解答") == 3
    assert sum(1 for item in items if item.difficulty == 2) == 3
    assert sum(1 for item in items if item.difficulty == 3) == 3
    assert all(item.parts.total > 0 for item in items)


def test_select_items_is_seed_deterministic_and_order_independent() -> None:
    constraints = make_constraints(total_questions=5, total_score_target=40)
    pool = tuple(
        cand(index, last_done_at=NOW - timedelta(days=14 + index)) for index in range(1, 11)
    )
    quotas = allocate_quotas(constraints, pool)
    first = select_items(constraints, pool, quotas, mastery_by_kp={}, now=NOW)
    second = select_items(constraints, pool, quotas, mastery_by_kp={}, now=NOW)
    reversed_pool = tuple(reversed(pool))
    third = select_items(
        constraints, reversed_pool, allocate_quotas(constraints, reversed_pool),
        mastery_by_kp={}, now=NOW,
    )
    assert first == second == third
    assert len(first) == 5


def test_select_items_sorts_like_a_real_paper() -> None:
    constraints = make_constraints(
        kp_ids=(KP_A, KP_B),
        total_questions=6,
        qtype_ratio={"单选": 1 / 3, "填空": 1 / 3, "解答": 1 / 3},
        difficulty_dist={2: 0.5, 4: 0.5},
        total_score_target=30,
    )
    combos = [
        (qtype, difficulty, kp_id)
        for qtype in ("单选", "填空", "解答")
        for difficulty in (2, 4)
        for kp_id in (KP_A, KP_B)
    ]
    # 每个 (题型, 难度, 知识点) 格子放 4 份，保证贪心不会因格子耗尽而提前卡住
    pool = tuple(
        cand(1 + copy_index * len(combos) + combo_index,
             qtype=qtype, difficulty=difficulty, kps=[(kp_id, 1.0)])
        for copy_index in range(4)
        for combo_index, (qtype, difficulty, kp_id) in enumerate(combos)
    )
    quotas = allocate_quotas(constraints, pool)
    items = select_items(constraints, pool, quotas, mastery_by_kp={}, now=NOW)
    assert len(items) == 6
    order_index = {qtype: index for index, qtype in enumerate(QTYPE_ORDER)}
    kp_order = {KP_A: 0, KP_B: 1}
    keys = [
        (
            order_index[item.qtype],
            item.difficulty,
            kp_order[item.kp_ids[0]],
            item.question_id,
        )
        for item in items
    ]
    assert keys == sorted(keys)
```

（注意：`QTYPE_ORDER` 也要加进 import 块。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: FAIL — `ImportError: cannot import name 'select_items'`

- [ ] **Step 3: 写实现**

在 `score_parts` 之后追加：

```python
def select_items(
    constraints: PaperConstraints,
    pool: Sequence[CandidateQuestion],
    quotas: QuotaPlan,
    *,
    mastery_by_kp: Mapping[int, float],
    now: datetime,
) -> tuple[PaperItem, ...]:
    """贪心选取：每步在可行题里取分最高者；同分由种子洗牌决定（spec §4.5）。"""
    _require_aware(now, "now")
    if not pool:
        return ()
    rng = random.Random(constraints.seed)
    order = sorted(pool, key=lambda candidate: candidate.question_id)
    rng.shuffle(order)
    position = {
        candidate.question_id: index for index, candidate in enumerate(order)
    }
    parts = {
        candidate.question_id: score_parts(
            candidate=candidate,
            constraints=constraints,
            mastery_by_kp=mastery_by_kp,
            now=now,
        )
        for candidate in order
    }
    remaining_qtype = dict(quotas.quota_by_qtype)
    remaining_difficulty = dict(quotas.target_by_difficulty)
    remaining_kp = dict(quotas.target_by_kp)
    score_map = constraints.score_map
    kp_order = {
        kp_id: index for index, kp_id in enumerate(constraints.kp_ids)
    }
    selected: dict[int, CandidateQuestion] = {}
    for _ in range(constraints.total_questions):
        feasible = [
            candidate
            for candidate in order
            if candidate.question_id not in selected
            and remaining_qtype.get(candidate.qtype, 0) > 0
            and remaining_difficulty.get(candidate.difficulty, 0) > 0
        ]
        if not feasible:
            break
        advancing = [
            candidate
            for candidate in feasible
            if any(
                remaining_kp.get(kp_id, 0) > 0
                for kp_id, _weight in candidate.kp_weights
            )
        ]
        bucket = advancing or feasible
        best = max(
            bucket,
            key=lambda candidate: (
                parts[candidate.question_id].total,
                -position[candidate.question_id],
            ),
        )
        selected[best.question_id] = best
        remaining_qtype[best.qtype] -= 1
        remaining_difficulty[best.difficulty] -= 1
        for kp_id, _weight in best.kp_weights:
            if remaining_kp.get(kp_id, 0) > 0:
                remaining_kp[kp_id] -= 1
    items = [
        PaperItem(
            question_id=candidate.question_id,
            qtype=candidate.qtype,
            difficulty=candidate.difficulty,
            score=int(score_map[candidate.qtype]),
            kp_ids=tuple(
                sorted(
                    (kp_id for kp_id, _weight in candidate.kp_weights),
                    key=lambda kp_id: kp_order.get(kp_id, len(kp_order)),
                )
            ),
            parts=parts[candidate.question_id],
        )
        for candidate in selected.values()
    ]
    items.sort(
        key=lambda item: (
            QTYPE_ORDER.index(item.qtype),
            item.difficulty,
            min(
                (kp_order.get(kp_id, len(kp_order)) for kp_id in item.kp_ids),
                default=len(kp_order),
            ),
            item.question_id,
        )
    )
    return tuple(items)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/paper_service.py backend/tests/test_paper.py
git commit -m "feat(s5-1): 组卷贪心选取、种子复现与试卷排序"
```

---

### Task 5: `plan_paper` 组装 + 三类 shortage + 端到端场景

**Files:**
- Modify: `backend/app/services/paper_service.py`（在 `select_items` 之后追加）
- Modify: `backend/tests/test_paper.py`

**Interfaces:**
- Consumes: 前四任务全部公开函数与数据类
- Produces: `plan_paper(constraints, candidates, *, mastery_by_kp=None, now=None) -> PaperPlan`

- [ ] **Step 1: 写失败测试**

import 块补 `plan_paper`，末尾追加：

```python
def test_plan_paper_happy_path_has_no_violation() -> None:
    plan = plan_paper(make_constraints(), many(10), mastery_by_kp={}, now=NOW)
    assert plan.ok is True
    assert len(plan.items) == 10
    assert plan.total_score == 80
    assert plan.violations == ()
    assert plan.counts_by_qtype == {"解答": 10}
    assert plan.counts_by_difficulty == {3: 10}
    assert plan.counts_by_kp == {KP_A: 10}


def test_plan_paper_reports_kp_shortage() -> None:
    constraints = make_constraints(kp_ids=(KP_A, KP_B), total_questions=10, total_score_target=80)
    candidates = many(2, start=1, kps=[(KP_A, 1.0)]) + many(10, start=11, kps=[(KP_B, 1.0)])
    plan = plan_paper(constraints, candidates, mastery_by_kp={}, now=NOW)
    assert plan.ok is False
    assert [violation.code for violation in plan.violations] == ["KP_SHORTAGE"]
    assert plan.violations[0].detail == {
        "kp_id": KP_A,
        "need": 5,
        "selected": 2,
        "available": 2,
    }
    assert len(plan.items) == 10
    assert plan.counts_by_kp == {KP_A: 2, KP_B: 8}


def test_plan_paper_reports_difficulty_shortage() -> None:
    constraints = make_constraints(
        total_questions=10, difficulty_dist={5: 0.5, 3: 0.5}, total_score_target=80
    )
    plan = plan_paper(constraints, many(20, difficulty=3), mastery_by_kp={}, now=NOW)
    assert plan.ok is False
    assert [violation.code for violation in plan.violations] == ["DIFFICULTY_SHORTAGE"]
    assert plan.violations[0].detail == {
        "difficulty": 5,
        "need": 5,
        "selected": 0,
        "available": 0,
    }
    assert len(plan.items) == 10
    assert all(item.difficulty == 3 for item in plan.items)


def test_plan_paper_excludes_recent_questions() -> None:
    constraints = make_constraints(total_questions=7, total_score_target=56)
    candidates = many(7, start=1, last_done_at=NOW - timedelta(days=15)) + many(
        3, start=101, last_done_at=NOW - timedelta(days=3)
    )
    plan = plan_paper(constraints, candidates, mastery_by_kp={}, now=NOW)
    assert plan.ok is True
    assert [item.question_id for item in plan.items] == list(range(1, 8))


def test_plan_paper_returns_no_candidates_plan() -> None:
    plan = plan_paper(
        make_constraints(), [cand(1, kps=[(999, 1.0)])], mastery_by_kp={}, now=NOW
    )
    assert plan.ok is False
    assert [violation.code for violation in plan.violations] == ["NO_CANDIDATES"]
    assert plan.violations[0].detail == {"available": 0, "excluded_recent": 0}
    assert plan.items == ()
    assert plan.total_score == 0
    assert plan.counts_by_qtype == {"解答": 0}
    assert plan.quota_by_qtype == {"解答": 10}


def test_plan_paper_all_recent_gives_no_candidates_with_count() -> None:
    plan = plan_paper(
        make_constraints(),
        many(10, last_done_at=NOW - timedelta(days=3)),
        mastery_by_kp={},
        now=NOW,
    )
    assert [violation.code for violation in plan.violations] == ["NO_CANDIDATES"]
    assert plan.violations[0].detail == {"available": 0, "excluded_recent": 10}


def test_plan_paper_accepts_score_within_tolerance() -> None:
    plan = plan_paper(
        make_constraints(
            total_questions=20,
            qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
            total_score_target=94,
        ),
        mixed_pool(),
        mastery_by_kp={},
        now=NOW,
    )
    assert plan.ok is True
    assert plan.total_score == 94
    assert plan.quota_by_qtype == {"单选": 10, "填空": 4, "解答": 6}


def test_plan_paper_tunes_qtype_counts_for_score() -> None:
    plan = plan_paper(
        make_constraints(
            total_questions=20,
            qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
            total_score_target=100,
        ),
        mixed_pool(),
        mastery_by_kp={},
        now=NOW,
    )
    assert plan.ok is True
    assert plan.quota_by_qtype == {"单选": 9, "填空": 4, "解答": 7}
    assert plan.total_score == 99


def test_plan_paper_reports_unreachable_total_score() -> None:
    plan = plan_paper(
        make_constraints(
            total_questions=20,
            qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
            total_score_target=200,
        ),
        mixed_pool(),
        mastery_by_kp={},
        now=NOW,
    )
    assert plan.ok is False
    codes = [violation.code for violation in plan.violations]
    assert "TOTAL_SCORE_OUT_OF_TOLERANCE" in codes
    assert plan.total_score == 94
    violation = next(
        item for item in plan.violations if item.code == "TOTAL_SCORE_OUT_OF_TOLERANCE"
    )
    assert violation.detail["target"] == 200
    assert violation.detail["achieved"] == 94


def test_plan_paper_surfaces_rounding_warning() -> None:
    plan = plan_paper(
        make_constraints(
            total_questions=9,
            qtype_ratio={"单选": 0.01, "解答": 0.99},
            difficulty_dist={3: 1.0},
            total_score_target=72,
        ),
        mixed_pool(),
        mastery_by_kp={},
        now=NOW,
    )
    assert plan.ok is True
    assert plan.warnings == ("题型「单选」按配比取整为 0 题",)
    assert plan.counts_by_qtype == {"单选": 0, "解答": 9}


def test_plan_paper_steers_difficulty_by_mastery() -> None:
    constraints = make_constraints(
        kp_ids=(KP_A, KP_B),
        total_questions=2,
        qtype_ratio={"解答": 1.0},
        difficulty_dist={2: 0.5, 5: 0.5},
        total_score_target=16,
    )
    candidates = [
        cand(1, difficulty=2, kps=[(KP_A, 1.0)]),
        cand(2, difficulty=5, kps=[(KP_A, 1.0)]),
        cand(3, difficulty=2, kps=[(KP_B, 1.0)]),
        cand(4, difficulty=5, kps=[(KP_B, 1.0)]),
    ]
    plan = plan_paper(
        constraints, candidates, mastery_by_kp={KP_A: 0.9, KP_B: 0.1}, now=NOW
    )
    assert plan.ok is True
    chosen = {item.kp_ids[0]: item.difficulty for item in plan.items}
    assert chosen == {KP_A: 5, KP_B: 2}


def test_plan_paper_dedupes_by_question_id_keeping_first() -> None:
    constraints = make_constraints(
        total_questions=2, difficulty_dist={2: 1.0}, total_score_target=16
    )
    plan = plan_paper(
        constraints,
        [cand(1, difficulty=2), cand(1, difficulty=3), cand(2, difficulty=2)],
        mastery_by_kp={},
        now=NOW,
    )
    assert plan.ok is True
    assert [item.question_id for item in plan.items] == [1, 2]
    assert plan.items[0].difficulty == 2


def test_plan_paper_rejects_naive_now() -> None:
    with pytest.raises(PaperPlanError, match="now"):
        plan_paper(
            make_constraints(), many(10), mastery_by_kp={}, now=datetime(2026, 11, 13, 9, 0)
        )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: FAIL — `ImportError: cannot import name 'plan_paper'`

- [ ] **Step 3: 写实现**

在 `select_items` 之后追加：

```python
def plan_paper(
    constraints: PaperConstraints,
    candidates: Sequence[CandidateQuestion],
    *,
    mastery_by_kp: Mapping[int, float] | None = None,
    now: datetime | None = None,
) -> PaperPlan:
    """组卷主入口：过滤 → 配额 → 选材 → 汇总；约束不足返回 violation 而不是抛错。"""
    moment = now or datetime.now(timezone.utc)
    _require_aware(moment, "now")
    moment = _as_utc(moment)
    mastery = dict(mastery_by_kp or {})
    pool, excluded_recent = prepare_pool(constraints, candidates, now=moment)
    quotas = allocate_quotas(constraints, pool)
    counts_qtype = {qtype: 0 for qtype in constraints.qtype_ratio}
    counts_difficulty = {difficulty: 0 for difficulty in sorted(constraints.difficulty_dist)}
    counts_kp = {kp_id: 0 for kp_id in constraints.kp_ids}
    if not pool:
        return PaperPlan(
            ok=False,
            items=(),
            total_score=0,
            target_score=constraints.total_score_target,
            quota_by_qtype=quotas.quota_by_qtype,
            quota_by_difficulty=quotas.quota_by_difficulty,
            quota_by_kp=quotas.quota_by_kp,
            counts_by_qtype=counts_qtype,
            counts_by_difficulty=counts_difficulty,
            counts_by_kp=counts_kp,
            violations=(
                Violation(
                    code="NO_CANDIDATES",
                    message="没有可用候选题（题库为空或全部被近期排除）",
                    detail={"available": 0, "excluded_recent": excluded_recent},
                ),
            ),
            warnings=quotas.warnings,
            seed=constraints.seed,
        )
    items = select_items(constraints, pool, quotas, mastery_by_kp=mastery, now=moment)
    available_qtype = _count_by_qtype(pool)
    available_difficulty = _count_by_difficulty(pool)
    available_kp = _count_by_kp(pool)
    for item in items:
        counts_qtype[item.qtype] = counts_qtype.get(item.qtype, 0) + 1
        counts_difficulty[item.difficulty] = counts_difficulty.get(item.difficulty, 0) + 1
        for kp_id in item.kp_ids:
            counts_kp[kp_id] = counts_kp.get(kp_id, 0) + 1
    violations: list[Violation] = []
    for qtype in QTYPE_ORDER:
        if qtype not in quotas.quota_by_qtype:
            continue
        need = quotas.quota_by_qtype[qtype]
        selected = counts_qtype.get(qtype, 0)
        if selected < need:
            violations.append(
                Violation(
                    code="QTYPE_SHORTAGE",
                    message=f"题型「{qtype}」题量不足：需要 {need} 道，实际 {selected} 道",
                    detail={
                        "qtype": qtype,
                        "need": need,
                        "selected": selected,
                        "available": available_qtype.get(qtype, 0),
                    },
                )
            )
    for difficulty in sorted(quotas.quota_by_difficulty):
        need = quotas.quota_by_difficulty[difficulty]
        selected = counts_difficulty.get(difficulty, 0)
        if selected < need:
            violations.append(
                Violation(
                    code="DIFFICULTY_SHORTAGE",
                    message=f"难度 {difficulty} 的题量不足：需要 {need} 道，实际 {selected} 道",
                    detail={
                        "difficulty": difficulty,
                        "need": need,
                        "selected": selected,
                        "available": available_difficulty.get(difficulty, 0),
                    },
                )
            )
    for kp_id in constraints.kp_ids:
        need = quotas.quota_by_kp[kp_id]
        selected = counts_kp.get(kp_id, 0)
        if selected < need:
            violations.append(
                Violation(
                    code="KP_SHORTAGE",
                    message=f"知识点 {kp_id} 覆盖不足：需要 {need} 道，实际 {selected} 道",
                    detail={
                        "kp_id": kp_id,
                        "need": need,
                        "selected": selected,
                        "available": available_kp.get(kp_id, 0),
                    },
                )
            )
    if quotas.score_out_of_tolerance:
        violations.append(
            Violation(
                code="TOTAL_SCORE_OUT_OF_TOLERANCE",
                message=(
                    f"总分 {quotas.planned_total_score} 不在目标 "
                    f"{constraints.total_score_target}±{quotas.tolerance} 内"
                ),
                detail={
                    "target": constraints.total_score_target,
                    "achieved": quotas.planned_total_score,
                    "tolerance": quotas.tolerance,
                    "suggestion": "调整题型配比或分值表，或放宽容差",
                },
            )
        )
    return PaperPlan(
        ok=not violations,
        items=items,
        total_score=sum(item.score for item in items),
        target_score=constraints.total_score_target,
        quota_by_qtype=quotas.quota_by_qtype,
        quota_by_difficulty=quotas.quota_by_difficulty,
        quota_by_kp=quotas.quota_by_kp,
        counts_by_qtype=counts_qtype,
        counts_by_difficulty=counts_difficulty,
        counts_by_kp=counts_kp,
        violations=tuple(violations),
        warnings=quotas.warnings,
        seed=constraints.seed,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q`
Expected: PASS

- [ ] **Step 5: 跑全量回归**

Run: `cd /e/BiShe-AIStudy/study-agent/backend && ../.venv/Scripts/python.exe -m pytest -q`
Expected: `1201 + 新增` passed，0 failed（S4-8 基线 1201）

- [ ] **Step 6: 提交**

```bash
cd /e/BiShe-AIStudy/study-agent
git add backend/app/services/paper_service.py backend/tests/test_paper.py
git commit -m "feat(s5-1): 组卷主流程、三类 shortage 与总分容差 violation"
```

---

### Task 6: 真实验收（10 份卷子）+ 文档同步

**Files:**
- Create: `/e/BiShe-AIStudy/.sdd/s5-1/accept.py`（**仓库外**，不入库）
- Create: `/e/BiShe-AIStudy/.sdd/s5-1/acceptance-evidence.md`（仓库外）
- Modify: `docs/PROGRESS.md`、`docs/DECISIONS.md`（D-058）、`AGENTS.md`（§9.6 锚点）、`docs/AI协作开发实施计划.md`（S5-1 勾选）

**Interfaces:**
- Consumes: `plan_paper`、`CandidateQuestion`、`PaperConstraints`、`mastery_service.decayed_mastery`
- Produces: 验收证据（真实题库一轮 + 构造数据一轮）

- [ ] **Step 1: 起环境并确认真实题库**

```bash
cd /e/BiShe-AIStudy/study-agent
docker compose -f deploy/docker-compose.dev.yml up -d
../.venv/Scripts/python.exe scripts/check_services.py   # 3/3 OK
```

（2026-11-13 实测：Postgres 16 + pgvector / Redis / MinIO 全绿；题库 56 题）

- [ ] **Step 2: 写验收脚本并跑 10 组约束**

创建 `/e/BiShe-AIStudy/.sdd/s5-1/accept.py`：

```python
"""S5-1 验收：真实题库跑 10 组约束，人工检查（仓库外脚本，不入库）。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "study-agent"
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from app.services.mastery_service import decayed_mastery  # noqa: E402
from app.services.paper_service import (  # noqa: E402
    CandidateQuestion,
    PaperConstraints,
    plan_paper,
)

load_dotenv(ROOT / ".env")
URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql")
USER_ID = int(os.environ.get("PAPER_DEMO_USER_ID", "50"))
NOW = datetime.now(timezone.utc)


def load(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            select q.id, q.qtype, q.difficulty, q.verified, q.origin,
                   array_agg(qk.kp_id order by qk.kp_id),
                   array_agg(coalesce(qk.weight, 1.0) order by qk.kp_id)
            from questions q
            join question_kps qk on qk.question_id = q.id
            group by q.id, q.qtype, q.difficulty, q.verified, q.origin
            order by q.id
            """
        )
        rows = cur.fetchall()
        cur.execute(
            "select question_id, greatest(last_review_at, created_at) from mistakes where user_id = %s",
            (USER_ID,),
        )
        done = {qid: moment for qid, moment in cur.fetchall() if moment is not None}
        cur.execute(
            "select kp_id, mastery, stability, last_practice_at from mastery where user_id = %s",
            (USER_ID,),
        )
        mastery = {}
        for kp_id, value, stability, last_practice in cur.fetchall():
            days = 0.0 if last_practice is None else max(
                0.0, (NOW - last_practice).total_seconds() / 86400.0
            )
            mastery[int(kp_id)] = decayed_mastery(float(value), float(stability), days=days)
        cur.execute(
            "select kp_id, count(*) from question_kps group by 1 order by 2 desc, 1 limit 6"
        )
        top_kps = tuple(row[0] for row in cur.fetchall())
    candidates = [
        CandidateQuestion(
            question_id=qid,
            qtype=qtype,
            difficulty=difficulty,
            kp_weights=tuple(zip(kps, weights)),
            verified=verified,
            origin=origin,
            last_done_at=done.get(qid),
        )
        for qid, qtype, difficulty, verified, origin, kps, weights in rows
    ]
    return candidates, mastery, top_kps


def scenarios(top_kps):
    """10 组约束；第 6/10 组会分别命中 NO_CANDIDATES 与总分不可达。"""
    first_kp = (top_kps[0],)
    return [
        ("1-20题标准卷",
         PaperConstraints(kp_ids=top_kps, total_questions=20,
                          qtype_ratio={"单选": 0.4, "填空": 0.2, "解答": 0.4},
                          difficulty_dist={1: 0.15, 2: 0.15, 3: 0.5, 4: 0.1, 5: 0.1},
                          total_score_target=100, seed=11)),
        ("2-10题小卷",
         PaperConstraints(kp_ids=top_kps, total_questions=10,
                          qtype_ratio={"单选": 0.4, "填空": 0.2, "解答": 0.4},
                          difficulty_dist={2: 0.5, 3: 0.5},
                          total_score_target=60, seed=12)),
        ("3-单知识点卷",
         PaperConstraints(kp_ids=first_kp, total_questions=5,
                          qtype_ratio={"解答": 1.0},
                          difficulty_dist={2: 0.5, 3: 0.5},
                          total_score_target=40, seed=13)),
        ("4-要求难题 d=5",
         PaperConstraints(kp_ids=top_kps, total_questions=10,
                          qtype_ratio={"解答": 1.0},
                          difficulty_dist={5: 0.5, 3: 0.5},
                          total_score_target=80, seed=14)),
        ("5-含多选题（题库 0 道）",
         PaperConstraints(kp_ids=top_kps, total_questions=10,
                          qtype_ratio={"多选": 0.2, "解答": 0.8},
                          difficulty_dist={3: 1.0},
                          total_score_target=72, seed=15)),
        ("6-知识点候选不足",
         PaperConstraints(kp_ids=(204, 133), total_questions=10,
                          qtype_ratio={"解答": 1.0},
                          difficulty_dist={3: 1.0},
                          total_score_target=80, seed=16)),
        ("7-解答占 80%",
         PaperConstraints(kp_ids=top_kps, total_questions=10,
                          qtype_ratio={"单选": 0.1, "解答": 0.9},
                          difficulty_dist={2: 0.5, 3: 0.5},
                          total_score_target=72, seed=17)),
        ("8-全难度 d=2",
         PaperConstraints(kp_ids=top_kps, total_questions=10,
                          qtype_ratio={"单选": 0.5, "解答": 0.5},
                          difficulty_dist={2: 1.0},
                          total_score_target=55, seed=18)),
        ("9-总分连续容差（目标 100，实得 94 量级）",
         PaperConstraints(kp_ids=top_kps, total_questions=20,
                          qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
                          difficulty_dist={2: 0.5, 3: 0.5},
                          total_score_target=100, seed=19)),
        ("10-总分不可达（目标 200）",
         PaperConstraints(kp_ids=top_kps, total_questions=20,
                          qtype_ratio={"单选": 0.5, "填空": 0.2, "解答": 0.3},
                          difficulty_dist={2: 0.5, 3: 0.5},
                          total_score_target=200, seed=20)),
    ]


def main() -> None:
    with psycopg.connect(URL) as conn:
        candidates, mastery, top_kps = load(conn)
    print(f"题库候选（有知识点链接）：{len(candidates)} 道；知识点前 6：{top_kps}")
    print(f"掌握度行：{sorted(mastery)}")
    for name, constraints in scenarios(top_kps):
        plan = plan_paper(constraints, candidates, mastery_by_kp=mastery, now=NOW)
        print(f"\n=== {name} ===")
        print(f"ok={plan.ok} 题量={len(plan.items)} 总分={plan.total_score}/{plan.target_score}")
        print(f"题型={plan.counts_by_qtype} 难度={plan.counts_by_difficulty}")
        print(f"知识点覆盖={plan.counts_by_kp}")
        for violation in plan.violations:
            print(f"  [violation] {violation.code}: {violation.message} {violation.detail}")
        for warning in plan.warnings:
            print(f"  [warning] {warning}")
        for index, item in enumerate(plan.items, start=1):
            print(f"  {index:02d}. id={item.question_id} {item.qtype} d={item.difficulty} "
                  f"score={item.score} kp={item.kp_ids} total={item.parts.total}")


if __name__ == "__main__":
    main()
```

Run:

```bash
cd /e/BiShe-AIStudy/study-agent
PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe ../.sdd/s5-1/accept.py > ../.sdd/s5-1/accept-real.out.txt 2>&1
tail -80 ../.sdd/s5-1/accept-real.out.txt
```

- [ ] **Step 3: 人工检查 10 份卷子并写证据**

逐条核对（写进 `acceptance-evidence.md`，**不许美化**）：

1. 第 1 组 20 题是否题型/难度接近配比、总分是否 100±5、kp 覆盖是否覆盖住前 6 个知识点
2. 第 2 组 10 题是否总量正确
3. 第 3 组单知识点卷是否所有题都挂该 kp
4. 第 4 组必须出现 `DIFFICULTY_SHORTAGE`（题库无 d=5）
5. 第 5 组必须出现 `QTYPE_SHORTAGE` 且 selected=0（题库无多选）
6. 第 6 组必须出现 `KP_SHORTAGE`
7. 第 7 组解答题是否占多数
8. 第 8 组是否全 d=2（若题库 d=2 只有 13 道，可能出现 `DIFFICULTY_SHORTAGE`，如实记录）
9. 第 9 组总分是否被邻域修正到容差内（或如实记录不可达）
10. 第 10 组必须出现 `TOTAL_SCORE_OUT_OF_TOLERANCE`
11. 排序：单选 → 多选 → 填空 → 解答，组内难度升序
12. `parts` 的四个分项是否都在 0–1、total 是否为加权和

证据文档结构（`.sdd/s5-1/acceptance-evidence.md`）：环境与时间、数据来源（真实题库 56 题，掌握度用户 50）、10 组逐条结论、发现的问题与处理、**未覆盖项**（浏览器/接口/落库均不在本卡）。

- [ ] **Step 4: 补一轮「近期全做过」构造数据**

真实库里用户 50 的错题只覆盖少量题，无法整卷排除，所以补一组构造数据（**明确标注构造**）：

```bash
cd /e/BiShe-AIStudy/study-agent
PYTHONIOENCODING=utf-8 ../.venv/Scripts/python.exe - <<'PY' > ../.sdd/s5-1/accept-constructed.out.txt 2>&1
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "backend")
from app.services.paper_service import CandidateQuestion, PaperConstraints, plan_paper

now = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
candidates = [
    CandidateQuestion(question_id=i, qtype="解答", difficulty=3,
                      kp_weights=((101, 1.0),), verified=True, origin="exam",
                      last_done_at=now - timedelta(days=3))
    for i in range(1, 11)
]
constraints = PaperConstraints(kp_ids=(101,), total_questions=10,
                               qtype_ratio={"解答": 1.0}, difficulty_dist={3: 1.0},
                               total_score_target=80)
plan = plan_paper(constraints, candidates, mastery_by_kp={}, now=now)
print("ok=", plan.ok, "items=", len(plan.items))
print([(v.code, v.detail) for v in plan.violations])
PY
cat ../.sdd/s5-1/accept-constructed.out.txt
```

Expected: `NO_CANDIDATES` + `excluded_recent=10`。

- [ ] **Step 5: 文档同步**

1. `docs/PROGRESS.md`
   - `### 阶段 5：练习与复习（M4）` 下 `- [ ] S5-1` 改 `- [x]`
   - 「当前状态」加一条完成记录：交付文件、18 组用例、全量 passed 数字、真实验收 10 组结论、**未覆盖项**
   - 「下一步」改为 S5-2（组卷 API + 预览页）
   - 「变更日志」加 `### 2026-11-13（S5-1）` 小节
2. `docs/DECISIONS.md` 新增 `## D-058 组卷分值/总分/难度/掌握度/贪心口径（S5-1）`，写清：题型固定分、总分=计数函数与 ±5% 容差、难度 1–5 权重表（3:5:2 展开规则）、未评估=0.5、`alloc` vs `target` 双配额、贪心+种子、5 个 violation 码
3. `AGENTS.md` §9.6 加一行锚点：`- 组卷样例：backend/app/services/paper_service.py + backend/tests/test_paper.py（prepare_pool → allocate_quotas → score_parts → select_items → plan_paper；纯函数无 DB；alloc 报 violation、target 做借位；同种子同结果）`
4. `docs/AI协作开发实施计划.md`：`[ ] S5-1 组卷算法 + 单测 ★关键` → `[x]`

- [ ] **Step 6: 最终验证 + 提交**

```bash
cd /e/BiShe-AIStudy/study-agent/backend
../.venv/Scripts/python.exe -m pytest tests/test_paper.py -q
../.venv/Scripts/python.exe -m pytest -q

cd /e/BiShe-AIStudy/study-agent
git add docs/PROGRESS.md docs/DECISIONS.md AGENTS.md docs/AI协作开发实施计划.md
git commit -m "docs(s5-1): 阶段 5 首卡验收记录与组卷口径定稿（D-058）"
```

Expected: 两次 pytest 全绿；`git status --short` 只剩 `.sdd` 之外无未跟踪代码文件。

---

## 自检（写完 plan 后已逐条核对）

- **Spec 覆盖**：题型固定分（Task 1/2）→ 总分容差（Task 2/5）→ 难度权重表（Task 2）→ 掌握度中性/联动（Task 3/5）→ 配额/借位（Task 2）→ 四维打分（Task 3）→ 贪心/种子/排序（Task 4）→ 5 类 violation（Task 5）→ 10 卷验收（Task 6）
- **占位符扫描**：无 TBD / 「类似上文」；每个代码步骤都有可复制代码
- **类型一致性**：`QuotaPlan` 的 `target_by_difficulty` / `target_by_kp` 只在 `select_items` 使用；`plan_paper` 用 `quota_by_*` 判 violation（与 spec §4.6 一致）；`planned_total_score` 与 spec 同名