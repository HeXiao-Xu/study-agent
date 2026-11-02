"""S4-1 题库出入参：字段与 SCHEMA §5.1 一一对应。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_QType = Literal["单选", "多选", "填空", "解答"]
_Origin = Literal["textbook", "exam", "mock", "upload", "ai"]


class OptionIn(BaseModel):
    key: str = Field(min_length=1, max_length=4)
    text: str = Field(min_length=1)


def validate_question_shape(*, qtype: str | None, option_keys: list[str] | None) -> None:
    """题型与选项必须自洽；抽成共享函数，手工新增/编辑与抽取路径用同一套规则。

    抛 ValueError 供 Pydantic 校验器使用；service 捕获后转 InvalidParamError(422)。
    """
    if qtype is None:
        return
    if qtype in {"单选", "多选"}:
        keys = option_keys or []
        if len(keys) < 2:
            raise ValueError("选择题至少需要 2 个选项")
        if len(set(keys)) != len(keys):
            raise ValueError("选项 key 重复")
    elif option_keys:
        raise ValueError("填空/解答题不应有选项")


class QuestionCreateIn(BaseModel):
    subject_id: int
    stem_md: str = Field(min_length=5)
    options: list[OptionIn] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: _QType
    difficulty: int = Field(ge=1, le=5)
    kp_ids: list[int] = Field(default_factory=list)
    origin: _Origin = "upload"
    tags: list[str] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "QuestionCreateIn":
        validate_question_shape(
            qtype=self.qtype,
            option_keys=[option.key for option in self.options] if self.options else None,
        )
        return self


class QuestionUpdateIn(BaseModel):
    """部分更新：出现在 model_fields_set 里的字段才生效；kp_ids=[] 表示清空关联。"""

    stem_md: str | None = Field(default=None, min_length=5)
    options: list[OptionIn] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    qtype: _QType | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    kp_ids: list[int] | None = None
    origin: _Origin | None = None
    tags: list[str] | None = None
    verified: bool | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "QuestionUpdateIn":
        # 只校验同时给出的 qtype/options；单独改 qtype 时要结合库中现有选项，
        # 由 service 对“更新后的有效状态”统一校验。
        if {"qtype", "options"} <= self.model_fields_set:
            validate_question_shape(
                qtype=self.qtype,
                option_keys=[option.key for option in self.options] if self.options else None,
            )
        return self


class QuestionSplitIn(BaseModel):
    split_at: str = Field(min_length=1, max_length=50, description="题干中出现、作为第二题起点开头的标记")


class QuestionMergeIn(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=10)


class KpRefOut(BaseModel):
    kp_id: int
    kp_name: str
    kp_code: str
    # DB 是 NUMERIC，但出参必须给前端 number；Decimal 会被 Pydantic 序列化成字符串。
    weight: float | None = None


class QuestionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    qtype: str
    difficulty: int
    origin: str
    verified: bool
    stem_md: str
    source_file_id: int | None = None
    created_by: int | None = None
    created_at: datetime
    kp_names: list[str] = Field(default_factory=list)


class QuestionDetailOut(QuestionSummaryOut):
    options_json: list[dict] | None = None
    answer_md: str | None = None
    analysis_md: str | None = None
    stem_latex: str | None = None
    tags: list[str] | None = None
    kps: list[KpRefOut] = Field(default_factory=list)
