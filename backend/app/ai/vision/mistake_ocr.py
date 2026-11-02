"""S4-2 拍照错题识别：一张图 → 结构化的一道题（spec §5.2）。

学生作答宁可为 null 也不猜（spec D-14）：错因诊断（S4-3）会把
my_answer_md 当证据，编造的作答会直接污染诊断结论。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.ai.extract.question_extractor import ExtractedOption
from app.ai.json_utils import loads_json_object
from app.ai.llm import LLMClient, LLMMessage, get_vision_client
from app.models.enums import LLMCallScene

# 复用 `mistake` 场景：llm_call_logs 的 CHECK 白名单在 0008 已固定
# （qa/query_rewrite/kp_align/embed/mistake/gen/agent），OCR 与后续 S4-3 诊断
# 同属错题场景，用 scene+model 即可区分；自造 "mistake_ocr" 会被 CHECK 静默拒绝，
# 视觉调用一条日志都落不了库。
SCENE = LLMCallScene.MISTAKE.value
PROMPT_FILE = "mistake_ocr_v1.md"
MAX_RETRIES = 2
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_ENV = Environment(loader=FileSystemLoader(_PROMPTS_DIR), undefined=StrictUndefined, autoescape=False)


class VisionError(Exception):
    """识别失败：mime 不支持、超限、JSON 非法、字段非法。"""


class VisionExtract(BaseModel):
    stem_md: str = Field(min_length=5)
    options: list[ExtractedOption] | None = None
    qtype: Literal["单选", "多选", "填空", "解答"]
    correct_answer_md: str | None = None
    my_answer_md: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_text(self) -> "VisionExtract":
        # 模型对空作答可能返回 "" 或空格串；统一成 None，避免下游把"有作答"误判成空证据
        self.stem_md = self.stem_md.strip()
        if not self.stem_md:
            raise ValueError("题干为空")
        for name in ("my_answer_md", "correct_answer_md"):
            value = getattr(self, name)
            if value is not None:
                cleaned = value.strip()
                setattr(self, name, cleaned or None)
        self.warnings = [warning.strip() for warning in self.warnings if warning.strip()]
        return self

    @model_validator(mode="after")
    def _validate_shape(self) -> "VisionExtract":
        if self.qtype in {"单选", "多选"}:
            options = self.options or []
            if len(options) < 2:
                raise ValueError("选择题至少需要 2 个选项")
            keys = [option.key for option in options]
            if len(set(keys)) != len(keys):
                raise ValueError("选项 key 重复")
        elif self.options:
            raise ValueError("填空/解答题不应有选项")
        return self


def render_prompt(*, subject_name: str) -> str:
    try:
        template = _ENV.get_template(PROMPT_FILE)
        return template.render(subject_name=subject_name)
    except Exception as exc:
        raise VisionError(f"prompt 渲染失败：{exc}") from exc


def extract_mistake(
    image_bytes: bytes,
    mime: str,
    *,
    subject_name: str,
    llm_client: LLMClient | None = None,
    max_retries: int = MAX_RETRIES,
) -> VisionExtract:
    if mime not in ALLOWED_MIMES:
        raise VisionError(f"不支持的图片类型：{mime}")
    if not image_bytes:
        raise VisionError("图片为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise VisionError("图片超过 8MB，请压缩后重试")

    client = llm_client or get_vision_client()
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
    messages = [
        LLMMessage(role="user", content=render_prompt(subject_name=subject_name), images=(data_url,))
    ]

    last_error: Exception | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        response = client.chat(messages, temperature=0.0, max_tokens=1500, scene=SCENE)
        try:
            payload = loads_json_object(response.text)
            return VisionExtract.model_validate(payload)
        except (ValidationError, ValueError) as exc:
            last_error = exc
    raise VisionError(f"识别失败（已尝试 {attempts} 次）：{last_error}")