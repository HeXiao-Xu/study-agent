"""S4-7 掌握度模型：7 天作答模拟 + 参数敏感性扫描（答辩材料）。

只调用纯函数，不连库、不调 LLM。用法：
    python scripts/mastery_sim.py
    python scripts/mastery_sim.py --k0 0.35 --grow 1.8 --difficulty 3

参数是「参考 SM-2 / FSRS 简化的工程取值」，不是拟合结果；敏感性扫描用来证明
结论（连续答对掌握度上升、间隔变长）不依赖某个精确参数。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import mastery_service as ms  # noqa: E402

PATTERN = [True, False, True, True, False, True, True]
"""7 天作答模式：对/错/对/对/错/对/对。第二天就错一次，好看出下降。"""

START = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def simulate_week(
    *, difficulty: int = 3, k0: float = ms.K0, grow: float = ms.STABILITY_GROW
) -> list[str]:
    original_k0, original_grow = ms.K0, ms.STABILITY_GROW
    ms.K0, ms.STABILITY_GROW = k0, grow
    try:
        state = ms.NEW_STATE
        lines = [f"7 天作答模拟（difficulty={difficulty}，K0={k0}，×{grow}）", ""]
        lines.append("天  结果   M      S       interval")
        for index, correct in enumerate(PATTERN):
            day = START + timedelta(days=index)
            state = ms.next_state(
                state, s=1.0 if correct else 0.0, difficulty=difficulty, now=day
            )
            interval = (
                (state.due_at - state.last_practice_at).days if state.due_at else 0
            )
            lines.append(
                f"{index + 1:>2}  {'对' if correct else '错':<4}  "
                f"{state.mastery:<6.3f} {state.stability:<6.2f} {interval:>3} 天"
            )
        lines.append("")
        lines.append(
            f"结算：M={state.mastery:.3f}  S={state.stability:.2f}  "
            f"attempts={state.attempts}  correct_cnt={state.correct_cnt}"
        )
        return lines
    finally:
        ms.K0, ms.STABILITY_GROW = original_k0, original_grow


def _five_correct(*, k0: float, grow: float, difficulty: int = 3) -> tuple[float, int]:
    original_k0, original_grow = ms.K0, ms.STABILITY_GROW
    ms.K0, ms.STABILITY_GROW = k0, grow
    try:
        state = ms.NEW_STATE
        for day in range(5):
            state = ms.next_state(
                state, s=1.0, difficulty=difficulty, now=START + timedelta(days=day)
            )
        interval = (state.due_at - state.last_practice_at).days if state.due_at else 0
        return state.mastery, interval
    finally:
        ms.K0, ms.STABILITY_GROW = original_k0, original_grow


def sensitivity_grid() -> list[str]:
    """K0 × 答对倍率的 3×3 扫描：连对 5 次后的 M 与间隔是否稳健。"""
    grows = (1.5, 1.8, 2.1)
    lines = [
        "",
        "敏感性扫描（d=3，连对 5 次后的 M / interval 天）",
        "K0 \\ 倍率  " + "  ".join(f"{g:<11.1f}" for g in grows),
    ]
    for k0 in (0.25, 0.35, 0.45):
        cells = []
        for grow in grows:
            mastery, interval = _five_correct(k0=k0, grow=grow)
            cells.append(f"{mastery:.3f}/{interval:<5}")
        lines.append(f"{k0:<9.2f} " + "  ".join(cells))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="掌握度模型模拟器")
    parser.add_argument("--difficulty", type=int, default=3)
    parser.add_argument("--k0", type=float, default=ms.K0)
    parser.add_argument("--grow", type=float, default=ms.STABILITY_GROW)
    args = parser.parse_args()
    print(
        "\n".join(
            simulate_week(
                difficulty=args.difficulty, k0=args.k0, grow=args.grow
            )
        )
    )
    print("\n".join(sensitivity_grid()))


if __name__ == "__main__":
    main()