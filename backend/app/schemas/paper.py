"""S5-2 组卷接口出入参（API.md §8）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import QuestionType

QTYPE_VALUES = tuple(item.value for item in QuestionType)
SEED_MAX = 2**31 - 1


class PaperConstraintIn(BaseModel):
    """generate / replace 共用约束（API.md §8）。"""

    kp_ids: list[int] = Field(min_length=1, max_length=500)
    total_questions: int = Field(ge=1, le=100)
    qtype_ratio: dict[str, float] = Field(min_length=1)
    difficulty_dist: dict[int, float] = Field(min_length=1)
    total_score: int = Field(ge=1, le=300)
    duration_min: int | None = Field(default=None, ge=1, le=1440)
    exclude_recent_days: int = Field(default=14, ge=0, le=365)
    seed: int | None = Field(default=None, ge=0, le=SEED_MAX)
    kp_weights: dict[int, float] | None = None

    @field_validator("kp_ids")
    @classmethod
    def _dedupe_kp_ids(cls, value: list[int]) -> list[int]:
        ordered: list[int] = []
        for kp_id in value:
            if kp_id not in ordered:
                ordered.append(kp_id)
        return ordered

    @field_validator("qtype_ratio")
    @classmethod
    def _validate_qtype_ratio(cls, value: dict[str, float]) -> dict[str, float]:
        if any(qtype not in QTYPE_VALUES for qtype in value):
            raise ValueError("题型占比里有不认识的题型，请只使用单选、多选、填空、解答")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("题型占比不能为负数")
        return value

    @field_validator("difficulty_dist")
    @classmethod
    def _validate_difficulty(cls, value: dict[int, float]) -> dict[int, float]:
        if any(difficulty not in range(1, 6) for difficulty in value):
            raise ValueError("难度只能在 1 到 5 之间")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("难度权重不能为负数")
        return value

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> Self:
        if sum(self.qtype_ratio.values()) <= 0:
            raise ValueError("请至少给一个题型设置占比")
        if sum(self.difficulty_dist.values()) <= 0:
            raise ValueError("请至少选择一个难度档位")
        if self.kp_weights is not None:
            if any(kp_id not in self.kp_ids for kp_id in self.kp_weights):
                raise ValueError("知识点权重只能设置已选中的知识点")
            if any(weight <= 0 for weight in self.kp_weights.values()):
                raise ValueError("知识点权重必须大于 0")
        return self


class PaperGenerateIn(PaperConstraintIn):
    """POST /papers/generate 入参：约束即入参。"""


class PaperReplaceIn(PaperConstraintIn):
    """POST /papers/replace-item 入参：约束平铺 + 卷面 + 要换掉的题。"""

    selected_question_ids: list[int] = Field(default_factory=list, max_length=100)
    replace_question_id: int = Field(ge=1)


class PaperSaveIn(BaseModel):
    """POST /papers 入参：保存草稿。"""

    title: str = Field(min_length=1, max_length=100)
    constraint: PaperConstraintIn
    question_ids: list[int] = Field(min_length=1, max_length=100)
    duration_min: int | None = Field(default=None, ge=1, le=1440)

    @field_validator("question_ids")
    @classmethod
    def _reject_duplicates(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("题目不能重复")
        return value


class ScorePartsOut(BaseModel):
    difficulty_match: float
    mastery_match: float
    novelty: float
    quality: float
    total: float


class OptionOut(BaseModel):
    key: str
    text: str


class PaperItemOut(BaseModel):
    question_id: int
    qtype: str
    difficulty: int
    score: int
    kp_ids: list[int]
    parts: ScorePartsOut | None = None
    subject_id: int
    stem_md: str
    options: list[OptionOut]
    answer_md: str | None
    analysis_md: str | None
    verified: bool
    origin: str


class PaperConstraintOut(BaseModel):
    """归一化后的约束回显（分值表也回显，便于前端解释总分）。"""

    kp_ids: list[int]
    total_questions: int
    qtype_ratio: dict[str, float]
    difficulty_dist: dict[int, float]
    total_score: int
    duration_min: int | None
    exclude_recent_days: int
    seed: int
    kp_weights: dict[int, float]
    score_by_qtype: dict[str, int]


class PaperViolationOut(BaseModel):
    code: str
    message: str
    detail: dict[str, Any]


class PaperPreviewOut(BaseModel):
    constraint: PaperConstraintOut
    seed: int
    ok: bool
    items: list[PaperItemOut]
    total_score: int
    target_score: int
    quota_by_qtype: dict[str, int]
    quota_by_difficulty: dict[int, int]
    quota_by_kp: dict[int, int]
    counts_by_qtype: dict[str, int]
    counts_by_difficulty: dict[int, int]
    counts_by_kp: dict[int, int]
    violations: list[PaperViolationOut]
    warnings: list[str]


class PaperReplaceOut(BaseModel):
    replaced: bool
    item: PaperItemOut | None = None
    reason: str | None = None


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    total_score: int
    duration_min: int | None
    question_ids: list[int]
    created_at: datetime


class PaperSummaryOut(BaseModel):
    """试卷列表行：不返回完整 question_ids，只给题数。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    total_score: int
    question_count: int
    created_at: datetime


class PaperDetailOut(PaperOut):
    constraint_json: dict[str, Any]
    items: list[PaperItemOut]
    missing_question_ids: list[int]