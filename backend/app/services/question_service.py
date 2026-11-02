"""S4-1 题库服务：规范化、两道闸判重、知识点对齐、CRUD 的唯一入口。

为什么不把判重放路由：切题任务与手动新增都必须走同一条判重链路，
放路由就会出现「任务绕过判重」的第二条写题路径。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.align.scoring import AUTO_THRESHOLD, ancestor_names, combine, cosine, keyword_score, tree_prior
from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.enums import UserRole
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.subject import Subject
from app.models.user import User
from app.schemas.question import QuestionCreateIn

TASK_QUESTION_EXTRACT = "question.extract"

DUPLICATE_COS_THRESHOLD = 0.92
ALIGN_TOP_K = 10
ALIGN_MAX_LINKS = 3
MANUAL_WEIGHT = Decimal("1.000000")
MAX_STEM_CHARS = 2000

_QUESTION_NO_PREFIX = re.compile(r"^\s*\d{1,2}\s*[.．、]\s*")
_EDGE_PUNCT = "，。；：、,.！？!?；:"
_LATEX_NOISE = re.compile(r"\$+|\\")


def normalize_stem(text: str) -> str:
    """去题号前缀 → NFKC 全角转半角 → 去空白 → 去首尾标点。

    不删数字、不删 LaTeX 反斜杠：它们是题干语义的一部分，
    归一化只抹平排版差异（空格/全角标点/题号）。
    """
    raw = _QUESTION_NO_PREFIX.sub("", (text or "").strip())
    half = unicodedata.normalize("NFKC", raw)
    no_space = re.sub(r"\s+", "", half)
    return no_space.strip(_EDGE_PUNCT)


def compute_stem_hash(text: str) -> str:
    return hashlib.sha256(normalize_stem(text).encode("utf-8")).hexdigest()


def embedding_text(stem_md: str) -> str:
    """向量化前去掉 LaTeX 定界符与反斜杠：$x$ 与 x 语义相同，留着只会稀释语义。"""
    return _LATEX_NOISE.sub(" ", (stem_md or ""))[:MAX_STEM_CHARS].strip()


def check_duplicate(
    session: Session, *, subject_id: int, stem_hash: str, vec: list[float] | None = None
) -> Question | None:
    """两道闸：哈希唯一（改标点仍命中）→ 向量余弦 ≥0.92（改数字/换语序仍命中）。"""
    hit = session.scalar(
        select(Question).where(Question.subject_id == subject_id, Question.stem_hash == stem_hash)
    )
    if hit is not None:
        return hit
    if not vec:
        return None
    nearest = session.scalar(
        select(Question)
        .where(Question.subject_id == subject_id, Question.embedding.is_not(None))
        .order_by(Question.embedding.cosine_distance(vec))
        .limit(1)
    )
    if nearest is not None and cosine(vec, list(nearest.embedding or [])) >= DUPLICATE_COS_THRESHOLD:
        return nearest
    return None


def align_knowledge_points(
    session: Session,
    *,
    subject_id: int,
    text: str,
    kp_names: list[str],
    vec: list[float],
    top_k: int = ALIGN_TOP_K,
    limit: int = ALIGN_MAX_LINKS,
) -> list[tuple[int, Decimal]]:
    """复用 S2-10 公式；LLM 的 kp_names 只当关键词信号，绝不直接落库。"""
    rows = [
        row
        for row in session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.subject_id == subject_id).order_by(KnowledgePoint.id)
        )
        if row.embedding is not None
    ]
    if not rows or not vec:
        return []
    by_id = {row.id: row for row in rows}
    anchors = " ".join(kp_names)
    ranked = sorted(rows, key=lambda row: cosine(vec, list(row.embedding or [])), reverse=True)[:top_k]
    picked: list[tuple[int, Decimal]] = []
    for row in ranked:
        score = combine(
            cosine(vec, list(row.embedding or [])),
            max(keyword_score(row.name, text), keyword_score(row.name, anchors)),
            tree_prior(row.level, ancestor_names(row, by_id), list(kp_names), text[:200]),
        )
        if score >= AUTO_THRESHOLD:
            picked.append((row.id, Decimal(str(round(score, 6)))))
    picked.sort(key=lambda item: item[1], reverse=True)
    return picked[:limit]


def ensure_can_edit(question: Question, viewer: User) -> None:
    """教师/管理员可改公共题库；学生只能改自己导入的题。"""
    if viewer.role in {UserRole.TEACHER.value, UserRole.ADMIN.value}:
        return
    if question.created_by is not None and question.created_by == viewer.id:
        return
    raise ForbiddenError("只能修改自己创建的题目")


def _ensure_subject(session: Session, subject_id: int) -> None:
    if session.get(Subject, subject_id) is None:
        raise NotFoundError("学科不存在")


def _ensure_kps_exist(session: Session, kp_ids: list[int]) -> None:
    if not kp_ids:
        return
    found = {row for row in session.scalars(select(KnowledgePoint.id).where(KnowledgePoint.id.in_(kp_ids)))}
    missing = sorted(set(kp_ids) - found)
    if missing:
        raise NotFoundError(f"知识点不存在：{missing}")


def _persist_question(
    session: Session,
    *,
    subject_id: int,
    origin: str,
    source_file_id: int | None,
    stem_md: str,
    options_json: list[dict] | None,
    answer_md: str | None,
    analysis_md: str | None,
    qtype: str,
    difficulty: int,
    tags: list[str] | None,
    verified: bool,
    embedding: list[float],
    created_by: int | None,
    links: list[tuple[int, Decimal]],
) -> Question:
    """建题 + 挂知识点；只 flush 不 commit（单题/批量两条路径共用）。"""
    question = Question(
        subject_id=subject_id,
        origin=origin,
        source_file_id=source_file_id,
        stem_md=stem_md,
        stem_hash=compute_stem_hash(stem_md),
        options_json=options_json,
        answer_md=answer_md,
        analysis_md=analysis_md,
        qtype=qtype,
        difficulty=difficulty,
        tags=tags,
        verified=verified,
        embedding=embedding,
        created_by=created_by,
    )
    session.add(question)
    session.flush()
    for kp_id, weight in links:
        session.add(QuestionKp(question_id=question.id, kp_id=kp_id, weight=weight))
    session.flush()
    return question


def _options_json_of(payload: QuestionCreateIn) -> list[dict] | None:
    return [option.model_dump() for option in payload.options] if payload.options else None


def create_question(
    session: Session, *, payload: QuestionCreateIn, creator: User, embedder: EmbeddingClient | None = None
) -> Question:
    """手动新增：判重命中直接 409（人工重复录入没有任何合理场景）。"""
    _ensure_subject(session, payload.subject_id)
    client = embedder or get_embedding_client()
    vec = client.encode([embedding_text(payload.stem_md)])[0]
    if check_duplicate(
        session, subject_id=payload.subject_id, stem_hash=compute_stem_hash(payload.stem_md), vec=vec
    ) is not None:
        raise ConflictError("题目已存在（题库里已有同一道题）")
    _ensure_kps_exist(session, payload.kp_ids)
    question = _persist_question(
        session,
        subject_id=payload.subject_id,
        origin=payload.origin,
        source_file_id=None,
        stem_md=payload.stem_md,
        options_json=_options_json_of(payload),
        answer_md=payload.answer_md,
        analysis_md=payload.analysis_md,
        qtype=payload.qtype,
        difficulty=payload.difficulty,
        tags=payload.tags,
        verified=False,
        embedding=vec,
        created_by=creator.id,
        links=[(kp_id, MANUAL_WEIGHT) for kp_id in payload.kp_ids],
    )
    session.commit()
    return question
