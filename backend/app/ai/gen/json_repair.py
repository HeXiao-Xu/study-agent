r"""S4-4 专用 JSON 解析兜底：修模型把 LaTeX 反斜杠漏转义的问题。

模型经常直接写 `\sqrt{7}` 而不是 JSON 要求的 `\\sqrt{7}`：
- 非法转义（`\s`、`\l`、`\c`…）会让 `json` 直接报错；
- "合法但语义错"的转义（`\frac`→换页符、`\neq`→换行、`\times`→制表符）更阴险——
  解析得过，但题面里混进控制字符，前端 KaTeX 与展示都会坏。

因此先按原样解析；命中上述任一症状再修一次。Prompt 已要求写双反斜杠，
这里只做兜底，不做无脑替换（正常文本里的换行不该被当成 LaTeX）。
"""
from __future__ import annotations

import re

from app.ai.json_utils import loads_json_object

# JSON 认的转义只有这些，其余 `\x` 一律非法；`(?<!\\)` 保证不动已正确转义的 `\\frac`
_INVALID_ESCAPE = re.compile(r'(?<!\\)\\(?!["\\/bfnrtu])')
# 单个反斜杠 + 字母（`\\frac` 这种已正确转义的不匹配）
_LETTER_ESCAPE = re.compile(r"(?<!\\)\\([A-Za-z])")
# "合法但语义错"：`\n`/`\t`/`\r`/`\b`/`\f` 后面还跟着 ≥2 个字母，说明本意是 LaTeX 命令
_SUSPICIOUS_ESCAPE = re.compile(r"(?<!\\)\\(?:n|t|r|b|f)[A-Za-z]{2,}")
_CONTROL_CHARS = ("\x08", "\x0b", "\x0c")


def _has_control_chars(payload: object) -> bool:
    if isinstance(payload, str):
        return any(char in payload for char in _CONTROL_CHARS)
    if isinstance(payload, dict):
        return any(_has_control_chars(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_control_chars(item) for item in payload)
    return False


def _needs_repair(payload: dict, text: str) -> bool:
    """解析成功也可能已经被悄悄弄坏（\\frac→换页符），这两种症状都要求重来一次。"""
    return _has_control_chars(payload) or bool(_SUSPICIOUS_ESCAPE.search(text))


def loads_lenient_json(text: str) -> dict:
    """按「原样 → 修非法转义 → 修全部反斜杠字母」三档解析，仍失败就让异常冒出去。"""
    payload: dict | None
    try:
        payload = loads_json_object(text)
    except ValueError:
        payload = None
    if payload is not None and not _needs_repair(payload, text):
        return payload

    repaired = _INVALID_ESCAPE.sub(r"\\\\", text)
    if payload is None:
        # 只有非法转义时才走中间档：能少改就少改
        try:
            return loads_json_object(repaired)
        except ValueError:
            pass
    return loads_json_object(_LETTER_ESCAPE.sub(r"\\\\\1", repaired))
