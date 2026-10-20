"""S1-3 中文分词工具测试：jieba 切词与 tsquery 安全（spec §6/§10）。"""
from __future__ import annotations

from app.utils.zh_tokenizer import build_tsquery, build_tsquery_or, join_for_tsv, tokenize_zh


def test_tokenize_zh_splits_chinese_words() -> None:
    tokens = tokenize_zh("函数的单调性：设 f(x) 在区间 D 内。")
    assert "函数" in tokens
    assert "单调性" in tokens
    assert "：" not in tokens
    assert "。" not in tokens
    assert all(" " not in token for token in tokens)


def test_tokenize_zh_filters_tsquery_operators() -> None:
    assert "&" not in tokenize_zh("函数 & 单调性")
    assert "|" not in tokenize_zh("函数 | 单调性")
    assert "(" not in tokenize_zh("f(x)")
    assert ")" not in tokenize_zh("f(x)")


def test_tokenize_zh_lowercases_latin() -> None:
    assert tokenize_zh("Function") == ["function"]


def test_math_userdict_keeps_domain_terms() -> None:
    """jieba 默认会拆「单调/性」；领域词典保证验收 SQL 的整词命中。"""
    for term in ("单调性", "定义域", "奇偶性", "周期性", "导数"):
        assert term in tokenize_zh(f"理解{term}的定义")


def test_tokenize_zh_empty_and_punctuation_only() -> None:
    assert tokenize_zh("") == []
    assert tokenize_zh("（）！？，。；：") == []


def test_join_for_tsv_uses_single_spaces() -> None:
    joined = join_for_tsv("函数的 单调性")
    assert "  " not in joined
    assert "函数" in joined
    assert "单调性" in joined


def test_build_tsquery_is_safe_and_ands_tokens() -> None:
    query = build_tsquery("函数的单调性")
    assert " & " in query
    for unsafe in ("&", "|", "!", "(", ")", ":", "*", "'"):
        if unsafe != "&":
            assert unsafe not in query
    assert build_tsquery("") == ""


def test_build_tsquery_or_dedupes_and_uses_or() -> None:
    query = build_tsquery_or("函数的定义域，函数的定义域")
    assert "|" in query
    assert "&" not in query
    parts = [part.strip() for part in query.split("|")]
    assert len(parts) == len(set(parts))
    assert parts.count("函数") == 1
    assert parts.count("定义域") == 1


def test_build_tsquery_or_empty() -> None:
    assert build_tsquery_or("  ，。！？ ") == ""
