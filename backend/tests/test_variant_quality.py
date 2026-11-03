"""S4-4 确定性质量护栏：同批题干指纹与「解析自问自答」标记。"""
from __future__ import annotations

from app.ai.gen.quality import find_self_talk, stem_fingerprint


def test_stem_fingerprint_ignores_spacing_and_fullwidth():
    assert stem_fingerprint("求 $a_7$　的值") == stem_fingerprint("求 $a_7$ 的值")
    assert stem_fingerprint("Ａ．$x=1$") == stem_fingerprint("A.$x=1$")


def test_stem_fingerprint_keeps_different_stems_apart():
    assert stem_fingerprint("求 $a_7$ 的值") != stem_fingerprint("求 $a_8$ 的值")


def test_find_self_talk_catches_reconsidering_phrases():
    """真机 m=48 变式1 的原文片段：写着「？错！重算…改为…」。"""
    text = "代入得 $-\\frac{3}{2}$？错！重算：改为 $\\int_2^4 x\\,dx$。"

    assert find_self_talk(text) == "？错"


def test_find_self_talk_passes_clean_analysis():
    assert find_self_talk("由通项公式 $a_n=a_1+(n-1)d$ 得 $d=3$。") is None


def test_find_self_talk_handles_none():
    assert find_self_talk("") is None