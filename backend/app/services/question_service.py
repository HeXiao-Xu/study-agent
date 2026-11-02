"""S4-1 题库服务：规范化、两道闸判重、知识点对齐、CRUD 的唯一入口。

为什么不把判重放路由：切题任务与手动新增都必须走同一条判重链路，
放路由就会出现「任务绕过判重」的第二条写题路径。
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import NoReturn

from sqlalchemy import Select, exists, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.align.extractor import AlignError, LlmMatch, extract_matches
from app.ai.align.scoring import (
    AUTO_THRESHOLD,
    LLM_MIN_CONFIDENCE,
    Candidate,
    ancestor_names,
    combine,
    cosine,
    keyword_score,
    tree_prior,
)
from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.ai.extract.question_extractor import ExtractedQuestion
from app.ai.llm import LLMError
from app.core.exceptions import ConflictError, ForbiddenError, InvalidParamError, NotFoundError
from app.models.enums import QuestionOrigin, UserRole
from app.models.knowledge_point import KnowledgePoint
from app.models.question import Question
from app.models.question_kp import QuestionKp
from app.models.subject import Subject
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.question import (
    KpRefOut,
    QuestionCreateIn,
    QuestionDetailOut,
    QuestionSummaryOut,
    QuestionUpdateIn,
    validate_question_shape,
)
from app.services.note_service import escape_like
from app.utils.pagination import PageParams, SortParams, apply_sort, paginate_query

TASK_QUESTION_EXTRACT = "question.extract"

DUPLICATE_COS_THRESHOLD = 0.92
ALIGN_TOP_K = 10
ALIGN_MAX_LINKS = 3
ALIGN_NOTE_TITLE = "试题"
MANUAL_WEIGHT = Decimal("1.000000")
MAX_STEM_CHARS = 2000

logger = logging.getLogger(__name__)

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
    session: Session,
    *,
    subject_id: int,
    stem_hash: str,
    vec: list[float] | None = None,
    exclude_ids: Sequence[int] | None = None,
) -> Question | None:
    """两道闸：哈希唯一（改标点仍命中）→ 向量余弦 ≥0.92（改数字/换语序仍命中）。

    exclude_ids 只给拆分/合并用：源题在提交前还留在库里，而拆出的两半/合并题干
    都是源题的子串或超串，向量必近邻；不排除源题会把「自己」判成重复。
    """
    excluded = tuple(exclude_ids or ())
    hash_query = select(Question).where(
        Question.subject_id == subject_id, Question.stem_hash == stem_hash
    )
    if excluded:
        hash_query = hash_query.where(Question.id.not_in(excluded))
    hit = session.scalar(hash_query)
    if hit is not None:
        return hit
    if not vec:
        return None
    nearest_query = select(Question).where(
        Question.subject_id == subject_id, Question.embedding.is_not(None)
    )
    if excluded:
        nearest_query = nearest_query.where(Question.id.not_in(excluded))
    nearest = session.scalar(
        nearest_query.order_by(Question.embedding.cosine_distance(vec)).limit(1)
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
    matcher: Callable[..., list[LlmMatch]] | None = None,
) -> list[tuple[int, Decimal]]:
    """向量召回 top-k 后由 LLM 在候选内选择：题目没有独立 prompt，借用 kp_align 的。

    为什么不沿用 0.75 门禁：题目↔知识点名的余弦上限只有 ~0.55，0.6*cos 最多 0.33，
    AUTO_THRESHOLD=0.75 对题目语料不可达（实测 20 题最高 0.688）。0.75 在 S2-10 是
    笔记对齐的「自动确认」线，不是「挂不挂」的线；挂载由 LLM 在候选内判断，
    combine 分只决定权重与排序。
    """
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
    candidates = [
        Candidate(
            kp_id=row.id,
            code=row.code,
            name=row.name,
            path=" / ".join([*reversed(ancestor_names(row, by_id)), row.name]),
            cos=cosine(vec, list(row.embedding or [])),
            keyword=max(keyword_score(row.name, text), keyword_score(row.name, anchors)),
            prior=tree_prior(row.level, ancestor_names(row, by_id), list(kp_names), text[:200]),
        )
        for row in ranked
    ]
    choose = matcher or extract_matches
    try:
        matches = choose(note_title=ALIGN_NOTE_TITLE, note_excerpt=text, candidates=candidates)
    except (AlignError, LLMError) as exc:
        # LLM 不可用不能连累建题：退回确定性打分，题目照样落库，只是链接可能偏少。
        logger.warning(
            "question_align_llm_failed",
            extra={"subject_id": subject_id, "error": str(exc)},
        )
        return _align_by_score(candidates, limit=limit)
    by_kp = {candidate.kp_id: candidate for candidate in candidates}
    picked: list[tuple[int, Decimal]] = []
    seen: set[int] = set()
    for match in matches:
        candidate = by_kp.get(match.kp_id)
        if candidate is None or match.kp_id in seen:
            continue
        if match.confidence < LLM_MIN_CONFIDENCE:
            continue
        seen.add(match.kp_id)
        picked.append(
            (candidate.kp_id, Decimal(str(round(combine(candidate.cos, candidate.keyword, candidate.prior), 6))))
        )
    picked.sort(key=lambda item: item[1], reverse=True)
    return picked[:limit]


def _align_by_score(candidates: list[Candidate], *, limit: int) -> list[tuple[int, Decimal]]:
    """LLM 失败时的兜底：仍按 S2-10 自动确认线，宁可少挂也不乱挂。"""
    picked: list[tuple[int, Decimal]] = []
    for candidate in candidates:
        score = combine(candidate.cos, candidate.keyword, candidate.prior)
        if score >= AUTO_THRESHOLD:
            picked.append((candidate.kp_id, Decimal(str(round(score, 6)))))
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


def _ensure_kps_exist(session: Session, *, subject_id: int, kp_ids: list[int]) -> None:
    """跨学科知识点与不存在同样处理：不泄露 id 是否真实存在，也避免挂错学科。"""
    if not kp_ids:
        return
    found = {
        row
        for row in session.scalars(
            select(KnowledgePoint.id).where(
                KnowledgePoint.id.in_(kp_ids), KnowledgePoint.subject_id == subject_id
            )
        )
    }
    missing = sorted(set(kp_ids) - found)
    if missing:
        raise InvalidParamError("知识点不存在或不属于该学科")


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
    try:
        session.flush()
    except IntegrityError as exc:
        # 判重是先查后写，两个并发请求可能同时通过；唯一约束才是最终裁决，
        # 这里把 DB 冲突翻译成 409，而不是让路由层看到 500。
        session.rollback()
        _translate_integrity_error(exc, message="题目已存在（题库里已有同一道题）")
    for kp_id, weight in links:
        session.add(QuestionKp(question_id=question.id, kp_id=kp_id, weight=weight))
    session.flush()
    return question


def _translate_integrity_error(exc: IntegrityError, *, message: str) -> NoReturn:
    """唯一约束是判重的最终裁决；只翻译题干唯一键，其余约束原样上抛。"""
    if "uq_questions_subject_stem_hash" in str(exc.orig):
        raise ConflictError(message) from exc
    raise exc


def _commit(session: Session, *, conflict_message: str = "题目已存在（题库里已有同一道题）") -> None:
    """提交失败先回滚再抛；UPDATE 撞题干唯一键与 INSERT 一样翻成 409。"""
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        _translate_integrity_error(exc, message=conflict_message)
    except Exception:
        session.rollback()
        raise


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
    # 重复 kp_id 会生成主键相同的 QuestionKp，flush 时直接炸唯一约束，入口先收敛
    kp_ids = list(dict.fromkeys(payload.kp_ids))
    _ensure_kps_exist(session, subject_id=payload.subject_id, kp_ids=kp_ids)
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
        links=[(kp_id, MANUAL_WEIGHT) for kp_id in kp_ids],
    )
    _commit(session)
    return question


def create_extracted_question(
    session: Session,
    *,
    extracted: ExtractedQuestion,
    subject_id: int,
    origin: str,
    created_by: int | None,
    source_file_id: int | None,
    vec: list[float],
) -> tuple[Question, bool]:
    """任务专用：返回 (题目, 是否命中重复)。不 commit —— 整卷由一个事务提交。

    重复题直接返回库里那道，不修改它：重复导入只补缺口，不覆盖人工修正。
    """
    if origin not in {item.value for item in QuestionOrigin}:
        raise InvalidParamError(f"非法的题目来源：{origin}")
    duplicate = check_duplicate(
        session, subject_id=subject_id, stem_hash=compute_stem_hash(extracted.stem_md), vec=vec
    )
    if duplicate is not None:
        return duplicate, True
    question = _persist_question(
        session,
        subject_id=subject_id,
        origin=origin,
        source_file_id=source_file_id,
        stem_md=extracted.stem_md,
        options_json=(
            [option.model_dump() for option in extracted.options] if extracted.options else None
        ),
        answer_md=extracted.answer_md,
        analysis_md=extracted.analysis_md,
        qtype=extracted.qtype,
        difficulty=extracted.difficulty,
        tags=None,
        verified=extracted.answer_source == "paper",
        embedding=vec,
        created_by=created_by,
        links=align_knowledge_points(
            session,
            subject_id=subject_id,
            text=extracted.stem_md,
            kp_names=extracted.kp_names,
            vec=vec,
        ),
    )
    return question, False


def _load_question(session: Session, question_id: int) -> Question:
    question = session.get(Question, question_id)
    if question is None:
        raise NotFoundError("题目不存在")
    return question


def _replace_links(session: Session, question_id: int, links: list[tuple[int, Decimal]]) -> None:
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    for kp_id, weight in links:
        session.add(QuestionKp(question_id=question_id, kp_id=kp_id, weight=weight))
    session.flush()


def _mistakes_table_exists(session: Session) -> bool:
    """S4-2 建 mistakes 表后自动生效；S4-1 阶段表不存在则无条件放行（spec D-15）。"""
    try:
        return inspect(session.get_bind()).has_table("mistakes")
    except Exception:  # noqa: BLE001 —— 拿不到连接时按“表不存在”处理，不阻塞题库操作
        return False


def _ensure_not_referenced(session: Session, question_ids: list[int]) -> None:
    if not _mistakes_table_exists(session):
        return
    row = session.execute(
        text("SELECT 1 FROM mistakes WHERE question_id = ANY(:ids) LIMIT 1"),
        {"ids": question_ids},
    ).first()
    if row is not None:
        raise ConflictError("题目已被错题本引用，不能删除、合并或拆分")


def _replace_stem(
    session: Session, question: Question, stem_md: str, *, embedder: EmbeddingClient | None = None
) -> None:
    new_hash = compute_stem_hash(stem_md)
    duplicate = check_duplicate(session, subject_id=question.subject_id, stem_hash=new_hash, vec=None)
    if duplicate is not None and duplicate.id != question.id:
        raise ConflictError("题目已存在（题库里已有同一道题）")
    vec = (embedder or get_embedding_client()).encode([embedding_text(stem_md)])[0]
    question.stem_md = stem_md
    question.stem_hash = new_hash
    question.embedding = vec
    _replace_links(
        session,
        question.id,
        align_knowledge_points(
            session, subject_id=question.subject_id, text=stem_md, kp_names=[], vec=vec
        ),
    )


def update_question(
    session: Session,
    *,
    question_id: int,
    payload: QuestionUpdateIn,
    viewer: User,
    embedder: EmbeddingClient | None = None,
) -> Question:
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    fields = payload.model_fields_set

    # 非空列（qtype/difficulty/origin/verified）传 null 是非法参数，必须在写库前拦成 422；
    # 不能落成 NULL 等 commit 时由 DB 抛 NotNullViolation（那会变成 500）。
    for name in ("qtype", "difficulty", "origin", "verified"):
        if name in fields and getattr(payload, name) is None:
            raise InvalidParamError(f"{name} 不能为 null")

    # 校验“更新后的有效状态”：只改 qtype 时选项来自库中现有值，所以不能只看 payload。
    effective_options = (
        ([option.model_dump() for option in payload.options] if payload.options else None)
        if "options" in fields
        else question.options_json
    )
    try:
        validate_question_shape(
            qtype=payload.qtype if "qtype" in fields else question.qtype,
            option_keys=[row["key"] for row in effective_options] if effective_options else None,
        )
    except ValueError as exc:
        raise InvalidParamError(str(exc)) from exc

    # 用原始串判等：只改空格/标点也要落库，否则前端回填旧文本、用户以为没保存。
    if "stem_md" in fields and payload.stem_md is not None:
        if payload.stem_md != question.stem_md:
            _replace_stem(session, question, payload.stem_md, embedder=embedder)
    if "options" in fields:
        question.options_json = effective_options
    for name in ("answer_md", "analysis_md", "tags"):
        if name in fields:
            setattr(question, name, getattr(payload, name))
    for name in ("qtype", "difficulty", "origin", "verified"):
        if name in fields:
            setattr(question, name, getattr(payload, name))
    if "kp_ids" in fields and payload.kp_ids is not None:
        kp_ids = list(dict.fromkeys(payload.kp_ids))
        _ensure_kps_exist(session, subject_id=question.subject_id, kp_ids=kp_ids)
        _replace_links(session, question.id, [(kp_id, MANUAL_WEIGHT) for kp_id in kp_ids])
    _commit(session)
    return question


def split_question(
    session: Session,
    *,
    question_id: int,
    split_at: str,
    viewer: User,
    embedder: EmbeddingClient | None = None,
) -> list[Question]:
    """把一道题按标记切成两道：AI 把两题串一起时的人工兜底。"""
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    marker = (split_at or "").strip()
    if not marker:
        raise InvalidParamError("split_at 不能为空")
    position = question.stem_md.find(marker)
    if position <= 0:
        raise InvalidParamError(f"题干中找不到可作为切分点的标记：{marker}")
    left = question.stem_md[:position].strip()
    right = question.stem_md[position:].strip()
    if len(normalize_stem(left)) < 5 or len(normalize_stem(right)) < 5:
        raise InvalidParamError("切分后任一半少于 5 个字，拒绝拆分")
    _ensure_not_referenced(session, [question_id])

    client = embedder or get_embedding_client()
    vectors = client.encode([embedding_text(left), embedding_text(right)])
    created: list[Question] = []
    for stem, vec in zip((left, right), vectors):
        if check_duplicate(
            session,
            subject_id=question.subject_id,
            stem_hash=compute_stem_hash(stem),
            vec=vec,
            exclude_ids=[question_id],
        ) is not None:
            raise ConflictError("拆分出的题目已存在于题库")
        created.append(
            _persist_question(
                session,
                subject_id=question.subject_id,
                origin=question.origin,
                source_file_id=question.source_file_id,
                stem_md=stem,
                options_json=question.options_json,
                answer_md=question.answer_md,
                analysis_md=question.analysis_md,
                qtype=question.qtype,
                difficulty=question.difficulty,
                tags=list(question.tags) if question.tags else None,
                verified=bool(question.verified),
                embedding=vec,
                created_by=question.created_by,
                links=align_knowledge_points(
                    session, subject_id=question.subject_id, text=stem, kp_names=[], vec=vec
                ),
            )
        )
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    session.delete(question)
    _commit(session, conflict_message="拆分出的题目已存在于题库")
    return created


def merge_questions(
    session: Session, *, ids: list[int], viewer: User, embedder: EmbeddingClient | None = None
) -> Question:
    """按 id 升序拼接：顺序影响题干可读性，必须确定，不能依赖入参顺序。"""
    unique_ids = sorted({int(item) for item in ids})
    if len(unique_ids) < 2:
        raise InvalidParamError("合并至少需要 2 道题")
    questions = [_load_question(session, item) for item in unique_ids]
    for question in questions:
        ensure_can_edit(question, viewer)
    if len({question.subject_id for question in questions}) != 1:
        raise InvalidParamError("只能合并同一学科的题目")
    _ensure_not_referenced(session, unique_ids)

    stem = "\n\n".join(question.stem_md for question in questions)
    answer = "\n\n".join(q.answer_md for q in questions if q.answer_md) or None
    analysis = "\n\n".join(q.analysis_md for q in questions if q.analysis_md) or None
    first = questions[0]
    vec = (embedder or get_embedding_client()).encode([embedding_text(stem)])[0]
    if check_duplicate(
        session,
        subject_id=first.subject_id,
        stem_hash=compute_stem_hash(stem),
        vec=vec,
        exclude_ids=unique_ids,
    ) is not None:
        raise ConflictError("合并后的题目已存在于题库")

    merged = _persist_question(
        session,
        subject_id=first.subject_id,
        origin=first.origin,
        source_file_id=first.source_file_id,
        stem_md=stem,
        options_json=None,
        answer_md=answer,
        analysis_md=analysis,
        qtype=first.qtype,
        difficulty=max(question.difficulty for question in questions),
        tags=None,
        verified=all(bool(question.verified) for question in questions),
        embedding=vec,
        created_by=first.created_by,
        links=align_knowledge_points(
            session, subject_id=first.subject_id, text=stem, kp_names=[], vec=vec
        ),
    )
    for question in questions:
        for row in list(
            session.scalars(select(QuestionKp).where(QuestionKp.question_id == question.id))
        ):
            session.delete(row)
        session.delete(question)
    _commit(session, conflict_message="合并后的题目已存在于题库")
    return merged


def delete_question(session: Session, *, question_id: int, viewer: User) -> None:
    question = _load_question(session, question_id)
    ensure_can_edit(question, viewer)
    _ensure_not_referenced(session, [question_id])
    for row in list(session.scalars(select(QuestionKp).where(QuestionKp.question_id == question_id))):
        session.delete(row)
    session.delete(question)
    _commit(session)


@dataclass(frozen=True)
class QuestionFilters:
    subject_id: int | None = None
    qtype: str | None = None
    kp_id: int | None = None
    origin: str | None = None
    created_by: int | None = None
    verified: bool | None = None
    keyword: str | None = None
    source_file_id: int | None = None


SORTABLE = {
    "created_at": Question.created_at,
    "id": Question.id,
    "difficulty": Question.difficulty,
}


def ensure_subject_exists(session: Session, subject_id: int) -> None:
    _ensure_subject(session, subject_id)


def build_questions_query(*, filters: QuestionFilters) -> Select:
    """题库是公共语料，不按 user_id 过滤（SCHEMA §5.1 的口径）。

    kp_id 用 EXISTS 而不是 join：join 会让一题多知识点时出现重复行，
    count 也跟着翻倍。
    """
    stmt = select(Question)
    if filters.subject_id is not None:
        stmt = stmt.where(Question.subject_id == filters.subject_id)
    if filters.qtype:
        stmt = stmt.where(Question.qtype == filters.qtype)
    if filters.origin:
        stmt = stmt.where(Question.origin == filters.origin)
    if filters.created_by is not None:
        stmt = stmt.where(Question.created_by == filters.created_by)
    if filters.source_file_id is not None:
        stmt = stmt.where(Question.source_file_id == filters.source_file_id)
    if filters.verified is not None:
        stmt = stmt.where(Question.verified.is_(filters.verified))
    if filters.keyword:
        pattern = f"%{escape_like(filters.keyword)}%"
        stmt = stmt.where(Question.stem_md.ilike(pattern, escape="\\"))
    if filters.kp_id is not None:
        stmt = stmt.where(
            exists().where(
                QuestionKp.question_id == Question.id, QuestionKp.kp_id == filters.kp_id
            )
        )
    return stmt


def _attach_kp_names(session: Session, items: list[QuestionSummaryOut]) -> None:
    """一页一次 IN 批查，避免逐题查库（AGENTS §4 禁止循环查库）。"""
    ids = [item.id for item in items]
    if not ids:
        return
    rows = session.execute(
        select(QuestionKp.question_id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKp.kp_id)
        .where(QuestionKp.question_id.in_(ids))
        .order_by(QuestionKp.weight.desc())
    ).all()
    grouped: dict[int, list[str]] = {}
    for question_id, name in rows:
        grouped.setdefault(question_id, []).append(name)
    for item in items:
        item.kp_names = grouped.get(item.id, [])


def list_questions(
    session: Session, *, filters: QuestionFilters, page: PageParams, sort: SortParams
) -> PageData[QuestionSummaryOut]:
    stmt = apply_sort(
        build_questions_query(filters=filters),
        sort_by=sort.sort_by,
        order=sort.order,
        allowed=SORTABLE,
        default_sort="created_at",
    )
    # 同一次导入的 created_at 相同，没有唯一 tiebreaker 时翻页会重复/漏行。
    stmt = stmt.order_by(Question.id.desc())
    data = paginate_query(session, stmt, page, item_model=QuestionSummaryOut)
    _attach_kp_names(session, data.items)
    return data


def get_question_detail(session: Session, *, question_id: int) -> QuestionDetailOut:
    question = _load_question(session, question_id)
    rows = session.execute(
        select(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.code,
            QuestionKp.weight,
        )
        .join(QuestionKp, QuestionKp.kp_id == KnowledgePoint.id)
        .where(QuestionKp.question_id == question_id)
        .order_by(QuestionKp.weight.desc())
    ).all()
    detail = QuestionDetailOut.model_validate(question)
    detail.kps = [
        KpRefOut(kp_id=row[0], kp_name=row[1], kp_code=row[2], weight=row[3]) for row in rows
    ]
    return detail
