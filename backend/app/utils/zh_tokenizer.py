"""中文分词工具：jieba 切词后写入 tsv，查询侧复用同一函数（spec §6）。

为什么不用 to_tsquery('chinese', ...)：PostgreSQL 没有中文内置分词；
为什么不用 bigram：SCHEMA §9 明确精度不如分词。
"""
from __future__ import annotations

import re
from pathlib import Path

import jieba

# jieba 默认词典会把「单调性」切成「单调/性」，导致领域检索词被拆碎；
# 用标准 userdict 机制补高中数学高频词（不是自写分词逻辑）
_DICT_PATH = Path(__file__).with_name("math_dict.txt")
if _DICT_PATH.exists():
    jieba.load_userdict(str(_DICT_PATH))

# 只保留中文/字母/数字/下划线；tsquery 操作符与标点一律丢弃，避免拼出非法查询
_TOKEN_RE = re.compile(r"^[\w\u4e00-\u9fff]+$", re.UNICODE)


def tokenize_zh(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    tokens: list[str] = []
    for raw in jieba.cut(text, cut_all=False):
        token = raw.strip().lower()
        if token and _TOKEN_RE.match(token):
            tokens.append(token)
    return tokens


def join_for_tsv(text: str) -> str:
    """写入侧：空格连接的词串，交给 to_tsvector('simple', ...)。"""
    return " ".join(tokenize_zh(text))


def build_tsquery(text: str) -> str:
    """查询侧：token 用 & 连接；空文本返回空串，调用方跳过全文查询。"""
    return " & ".join(tokenize_zh(text))
