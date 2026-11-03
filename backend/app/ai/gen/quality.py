r"""S4-4 确定性质量护栏：不经过 LLM 的两条硬检查。

真机验收抓到的两类坏题（`.sdd/s4-4/acceptance-evidence.md` 有原始记录）：
1. 同一批 3 道里出现两道题干完全相同（m=43 变式1 与变式3）；
2. 解析里整段"自问自答"——写着「？错！重算…改为 ∫_2^4 x dx」，把题干自己改了，
   答案也跟着错（m=48 变式1）。

这两类都不需要模型判断，纯字符串规则即可拦掉，比加第三个 LLM 判官便宜且可复现。
"""
from __future__ import annotations

import re
import unicodedata

# 出现任一即判「解析在自说自话」：这些词在正常解题里不该出现
SELF_TALK_MARKERS = (
    "？错",
    "?错",
    "错！",
    "重算",
    "重新计算",
    "再核",
    "改为",
    "换一道",
    "换一题",
    "修正题目",
    "但题目",
    "等等，",
    "让我重新",
    "重新写",
)

_SPACE = re.compile(r"\s+")


def stem_fingerprint(stem_md: str) -> str:
    """题干指纹：全角转半角 + 去空白，只用于同批查重（不替代题库的 stem_hash）。"""
    return _SPACE.sub("", unicodedata.normalize("NFKC", stem_md or ""))


def find_self_talk(analysis_md: str) -> str | None:
    """返回命中的第一个自问自答标记；没有则 None。"""
    text = analysis_md or ""
    for marker in SELF_TALK_MARKERS:
        if marker in text:
            return marker
    return None