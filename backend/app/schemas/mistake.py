"""S4-2 错题出入参（API.md §6 错题本）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import MISTAKE_STATUSES


class MistakeCreateIn(BaseModel):
    question_id: int = Field(gt=0)
    my_answer_md: str | None = None
    correct_answer_md: str | None = None


class MistakeUpdateIn(BaseModel):
    my_answer_md: str | None = None
    correct_answer_md: str | None = None
    status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_status(cls, data: object) -> object:
        # status 是 NOT NULL 列：显式传 null 与「不传」必须区分开，
        # 否则会把 500（DB 约束）暴露给前端。与 S4-1 PATCH 的 I1 口径一致。
        if isinstance(data, dict) and "status" in data and data["status"] is None:
            raise ValueError("status 不能为 null")
        return data

    @model_validator(mode="after")
    def _validate_status_value(self) -> "MistakeUpdateIn":
        if self.status is not None and self.status not in MISTAKE_STATUSES:
            options = "、".join(MISTAKE_STATUSES)
            raise ValueError(f"非法的错题状态：{self.status}（可选：{options}）")
        return self


class MistakeReviewIn(BaseModel):
    correct: bool


class OptionOut(BaseModel):
    key: str
    text: str


class MistakeVariantOut(BaseModel):
    """S4-4 变式题出参：只暴露通过自检的题，被丢弃的只在 variants_stats 里计数。"""

    variant_id: str
    stem_md: str
    options: list[OptionOut] | None = None
    answer_md: str
    analysis_md: str | None = None
    qtype: str
    difficulty: int
    self_check: str = "passed"
    accepted_question_id: int | None = None


class VariantsStatsOut(BaseModel):
    requested: int
    passed: int
    rejected: int
    rounds: int
    generated_at: datetime | None = None


class MistakeAnalysisOut(BaseModel):
    cause_type: str
    secondary_causes: list[str] = Field(default_factory=list)
    error_step: str | None = None
    explanation_md: str | None = None
    review_advice_md: str | None = None
    kp_ids: list[int] | None = None
    # 出参是数字（API.md §6）而不是 Decimal 字符串：DB 用 NUMERIC 存，DTO 转 float
    confidence: float | None = Field(default=None, ge=0, le=1)
    model: str | None = None
    prompt_version: str | None = None
    created_at: datetime
    # S4-4：未生成过是 null；已生成但 0 道通过时是空数组 + stats
    similar_questions: list[MistakeVariantOut] | None = None
    variants_stats: VariantsStatsOut | None = None


class VariantAcceptOut(BaseModel):
    question_id: int
    created: bool


class MistakeSummaryOut(BaseModel):
    id: int
    question_id: int
    status: str
    correct_streak: int
    stem_excerpt: str
    subject_id: int
    qtype: str
    difficulty: int
    kp_names: list[str] = Field(default_factory=list)
    cause_type: str | None = None
    has_image: bool = False
    created_at: datetime
    last_review_at: datetime | None = None


class MistakeDetailOut(MistakeSummaryOut):
    stem_md: str
    options: list[OptionOut] | None = None
    my_answer_md: str | None = None
    correct_answer_md: str | None = None
    image_url: str | None = None
    analysis: MistakeAnalysisOut | None = None


class MistakeCreateOut(MistakeDetailOut):
    created: bool


class StatusCountOut(BaseModel):
    status: str
    count: int


class CauseCountOut(BaseModel):
    cause_type: str
    count: int


class KpCountOut(BaseModel):
    kp_id: int
    kp_name: str
    count: int


class MistakeStatsOut(BaseModel):
    total: int
    by_status: list[StatusCountOut]
    by_cause: list[CauseCountOut]
    top_kps: list[KpCountOut]