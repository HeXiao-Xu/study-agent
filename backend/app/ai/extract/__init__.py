"""S4-1 试卷切题门面：splitter 出边界，question_extractor 出结构化结果。"""
from app.ai.extract.question_extractor import (
    ExtractedOption,
    ExtractedQuestion,
    ExtractResult,
    QuestionExtractError,
    extract_questions,
)
from app.ai.extract.splitter import QuestionBlock, SplitResult, split_questions

__all__ = [
    "ExtractResult",
    "ExtractedOption",
    "ExtractedQuestion",
    "QuestionBlock",
    "QuestionExtractError",
    "SplitResult",
    "extract_questions",
    "split_questions",
]