"""S4-2 拍照错题识别任务（spec §7）。

handler 不 commit：题目与错题由 runner 在同一事务里提交，
识别失败就让整条任务失败、图片仍留在 files（spec D-13）。
"""
from __future__ import annotations

import logging
import time
from io import BytesIO
from typing import Any

from sqlalchemy.orm import Session

from app.ai.embedding import get_embedding_client
from app.ai.extract import ExtractedQuestion
from app.ai.vision import extract_mistake
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.models.file import File
from app.models.subject import Subject
from app.services import mistake_service, question_service
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_MISTAKE_RECOGNIZE = mistake_service.TASK_MISTAKE_RECOGNIZE
_DEFAULT_SUBJECT_NAME = "高中数学"


@register(TASK_MISTAKE_RECOGNIZE)
def mistake_recognize_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    file_id = int(payload["file_id"])
    subject_id = int(payload["subject_id"])
    user_id = int(payload["user_id"])
    student_answer = (payload.get("my_answer_md") or "").strip() or None

    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if file.user_id != user_id:
        raise ForbiddenError("文件不属于当前用户")
    if file.mime not in mistake_service.IMAGE_MIMES:
        raise InvalidParamError("只能识别 PNG/JPEG 图片")

    buffer = BytesIO()
    get_storage().download_to(file.storage_path, buffer)
    vision = extract_mistake(
        buffer.getvalue(), file.mime, subject_name=_subject_name(session, subject_id)
    )

    extracted = ExtractedQuestion(
        stem_md=vision.stem_md,
        options=vision.options,
        answer_md=vision.correct_answer_md,
        analysis_md=None,
        qtype=vision.qtype,
        difficulty=3,
        kp_names=[],
        answer_source="paper" if vision.correct_answer_md else "none",
    )
    vec = get_embedding_client().encode([question_service.embedding_text(extracted.stem_md)])[0]
    question, reused_question = question_service.create_extracted_question(
        session,
        extracted=extracted,
        subject_id=subject_id,
        origin="upload",
        created_by=user_id,
        source_file_id=file_id,
        vec=vec,
    )

    # 作答优先级（R1）：学生手填 > 识别结果 > None，编造作答会污染 S4-3 诊断（D-14）。
    if student_answer is not None:
        my_answer, used_answer_source = student_answer, "student"
    elif vision.my_answer_md is not None:
        my_answer, used_answer_source = vision.my_answer_md, "vision"
    else:
        my_answer, used_answer_source = None, "none"

    mistake, created = mistake_service.task_create_mistake(
        session,
        user_id=user_id,
        question_id=question.id,
        my_answer_md=my_answer,
        correct_answer_md=vision.correct_answer_md or question.answer_md,
        image_file_id=file_id,
    )
    result = {
        "mistake_id": mistake.id,
        "question_id": question.id,
        "created": created,
        "reused_question": reused_question,
        "confidence": vision.confidence,
        "low_confidence": vision.confidence < mistake_service.LOW_CONFIDENCE,
        "used_answer_source": used_answer_source,
        "warnings": vision.warnings,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    logger.info(
        "mistake_recognize_done",
        # 不能用 "created"：与 LogRecord 的保留字段（时间戳）冲突，logging 直接抛 KeyError。
        extra={
            "file_id": file_id,
            "mistake_id": mistake.id,
            "reused_question": reused_question,
        },
    )
    return result


def _subject_name(session: Session, subject_id: int) -> str:
    """视觉提示必须跟学科走；查不到学科不阻断识别，回退默认并留 WARNING。"""
    subject = session.get(Subject, subject_id)
    if subject is None:
        logger.warning("mistake_recognize_subject_missing", extra={"subject_id": subject_id})
        return _DEFAULT_SUBJECT_NAME
    return subject.name
