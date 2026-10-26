"""S2-10 知识点对齐：打分与 LLM 候选内抽取。"""
from app.ai.align.extractor import AlignError, LlmMatch, extract_matches
from app.ai.align.scoring import (
    AUTO_THRESHOLD,
    LLM_MIN_CONFIDENCE,
    PENDING_THRESHOLD,
    TOP_K,
    Candidate,
    classify,
    combine,
    keyword_score,
    tree_prior,
)

__all__ = [
    "AUTO_THRESHOLD",
    "LLM_MIN_CONFIDENCE",
    "PENDING_THRESHOLD",
    "TOP_K",
    "AlignError",
    "Candidate",
    "LlmMatch",
    "classify",
    "combine",
    "extract_matches",
    "keyword_score",
    "tree_prior",
]