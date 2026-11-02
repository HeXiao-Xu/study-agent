"""S4-1 试卷切题任务：下载 → 解析 → 规则切题 → 逐题抽取 → 判重落库。

为什么不自行 commit：题目是整卷一个事务，半卷落库比零题更难收拾；
runner 统一提交/回滚，失败即全卷不落（单题失败走 failed_items，不算整卷失败）。
"""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.embedding import get_embedding_client
from app.ai.extract import ExtractResult, ExtractedQuestion, extract_questions, split_questions
from app.ai.llm import get_llm_client
from app.ai.parse import parse_document
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.core.storage import get_storage
from app.models.file import File
from app.models.subject import Subject
from app.services import question_service
from app.tasks.registry import register

logger = logging.getLogger(__name__)

TASK_QUESTION_EXTRACT = question_service.TASK_QUESTION_EXTRACT
_SUPPORTED_SUFFIXES = {".pdf", ".docx"}
_MAX_REASON_CHARS = 200


@register(TASK_QUESTION_EXTRACT)
def question_extract_task(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    file_id = int(payload["file_id"])
    subject_id = int(payload["subject_id"])
    origin = str(payload.get("origin") or "upload")
    owner_id = payload.get("created_by")

    file = session.get(File, file_id)
    if file is None:
        raise InvalidParamError("文件不存在")
    if owner_id is not None and file.user_id != int(owner_id):
        raise ForbiddenError("文件不属于当前用户")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise InvalidParamError(f"仅支持 PDF/DOCX 试卷，当前为 {suffix or '（无扩展名）'}")

    text = _load_text(file)
    split = split_questions(text)
    if not split.blocks:
        raise InvalidParamError("未识别到任何题目：" + "；".join(split.warnings))

    llm = get_llm_client()
    subject_name = _subject_name(session, subject_id)
    mode = "block" if split.degraded else "single"
    warnings = list(split.warnings)
    items: list[ExtractedQuestion] = []
    failed_items: list[dict[str, Any]] = []
    for block in split.blocks:
        try:
            result: ExtractResult = extract_questions(
                question_text=block.text,
                mode=mode,
                subject_name=subject_name,
                section_qtype=block.section_qtype,
                expected_count=split.expected_count if split.degraded else 1,
                llm_client=llm,
            )
        except Exception as exc:  # noqa: BLE001 —— 单题失败不该让整卷白切
            failed_items.append(
                {"index": block.index, "reason": str(exc)[:_MAX_REASON_CHARS]}
            )
            logger.warning(
                "question_extract_block_failed", extra={"file_id": file_id, "index": block.index}
            )
            continue
        if result.truncated:
            warnings.append(f"第 {block.index} 题区返回条数超过预期，已截断")
        items.extend(result.questions)

    if not items:
        raise InvalidParamError("全部题目抽取失败：" + "；".join(warnings))

    embedder = get_embedding_client()
    vectors = embedder.encode([question_service.embedding_text(item.stem_md) for item in items])

    created = duplicated = 0
    for extracted, vec in zip(items, vectors):
        _, is_duplicate = question_service.create_extracted_question(
            session,
            extracted=extracted,
            subject_id=subject_id,
            origin=origin,
            created_by=file.user_id,
            source_file_id=file.id,
            vec=vec,
        )
        if is_duplicate:
            duplicated += 1
        else:
            created += 1

    result_payload = {
        "file_id": file.id,
        "subject_id": subject_id,
        "detected_count": split.detected_count,
        "expected_count": split.expected_count,
        "created": created,
        "duplicated": duplicated,
        "failed_items": failed_items,
        "degraded": split.degraded,
        "warnings": warnings,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    logger.info(
        "question_extract_done",
        extra={"file_id": file.id, "created_count": created},
    )
    return result_payload


def _subject_name(session: Session, subject_id: int) -> str:
    """题面提示必须跟学科走；查不到学科不阻断切题，回退默认并留 WARNING。"""
    subject = session.get(Subject, subject_id)
    if subject is None:
        logger.warning("question_extract_subject_missing", extra={"subject_id": subject_id})
        return "高中数学"
    return subject.name


def _load_text(file: File) -> str:
    suffix = Path(file.filename).suffix.lower()
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(handle.name)
    try:
        with handle:
            get_storage().download_to(file.storage_path, handle)
        document = parse_document(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as exc:  # Windows 上解析器可能仍持有句柄
            logger.warning(
                "question_extract_tmp_cleanup_failed",
                extra={"file_id": file.id, "error": str(exc)},
            )
    if document.is_scanned:
        raise InvalidParamError("扫描版 PDF：无可抽取文本（拍照识别将在 S4-2 支持）")
    text = "\n".join(block.text.strip() for block in document.blocks if block.text.strip())
    if not text.strip():
        raise InvalidParamError("未解析出可用文本")
    return text