"""S2-10 对齐服务：向量补全、候选召回、打分落库、待确认队列。"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.align.extractor import extract_matches
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
from app.ai.embedding import EmbeddingClient, get_embedding_client
from app.ai.llm import LLMClient
from app.core.exceptions import InvalidParamError
from app.models.knowledge_point import KnowledgePoint
from app.models.note import Note
from app.models.note_kp import NoteKp
from app.models.user import User
from app.schemas.common import PageData
from app.schemas.kp_align import AlignBatchOut, AlignPair, PendingAlignOut
from app.utils.pagination import PageParams, paginate_query

_MAX_NOTE_CHARS = 2000


@dataclass(frozen=True)
class AlignStats:
    candidates: int
    matched: int
    auto: int
    pending: int
    dropped: int


def ensure_kp_embeddings(
    session: Session,
    *,
    subject_id: int | None,
    embedder: EmbeddingClient | None = None,
) -> int:
    client = embedder or get_embedding_client()
    stmt = select(KnowledgePoint)
    if subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == subject_id)
    rows = list(session.scalars(stmt.order_by(KnowledgePoint.id)))
    missing = [row for row in rows if row.embedding is None]
    if not missing:
        return 0
    by_id = {row.id: row for row in rows}
    texts = [_embedding_text(row, by_id) for row in missing]
    vectors = client.encode(texts)
    for row, vector in zip(missing, vectors, strict=True):
        row.embedding = vector
    session.flush()
    return len(missing)


def retrieve_candidates(
    session: Session,
    *,
    note: Note,
    note_vec: list[float],
    top_k: int = TOP_K,
) -> list[Candidate]:
    stmt = select(KnowledgePoint)
    if note.subject_id is not None:
        stmt = stmt.where(KnowledgePoint.subject_id == note.subject_id)
    rows = list(session.scalars(stmt.order_by(KnowledgePoint.id)))
    rows = [row for row in rows if row.embedding is not None]
    by_id = {row.id: row for row in rows}
    text = _note_text(note)
    scored: list[Candidate] = []
    for row in rows:
        ancestors = _ancestor_names(row, by_id)
        scored.append(
            Candidate(
                kp_id=row.id,
                code=row.code,
                name=row.name,
                path=" / ".join([*reversed(ancestors), row.name]),
                cos=_cosine(note_vec, list(row.embedding or [])),
                keyword=keyword_score(row.name, text),
                prior=tree_prior(row.level, ancestors, list(note.tags or []), note.title),
            )
        )
    scored.sort(key=lambda item: item.cos, reverse=True)
    return scored[:top_k]


def align_note(
    session: Session,
    *,
    note: Note,
    embedder: EmbeddingClient | None = None,
    llm_client: LLMClient | None = None,
) -> AlignStats:
    if not (note.content_text or "").strip():
        return AlignStats(0, 0, 0, 0, 0)
    text = _note_text(note)
    client = embedder or get_embedding_client()
    ensure_kp_embeddings(session, subject_id=note.subject_id, embedder=client)
    note_vec = client.encode([text[:_MAX_NOTE_CHARS]])[0]
    candidates = retrieve_candidates(session, note=note, note_vec=note_vec)
    old_rows = [
        row
        for row in session.scalars(
            select(NoteKp).where(NoteKp.note_id == note.id, NoteKp.source == "ai")
        )
        if row.source == "ai"
    ]
    if not candidates:
        for row in old_rows:
            session.delete(row)
        return AlignStats(0, 0, 0, 0, 0)
    matches = extract_matches(
        note_title=note.title,
        note_excerpt=text[:_MAX_NOTE_CHARS],
        candidates=candidates,
        llm_client=llm_client,
    )
    selected = {match.kp_id: match for match in matches}
    auto = pending = 0
    new_rows: list[NoteKp] = []
    for candidate in candidates:
        match = selected.get(candidate.kp_id)
        if match is None or match.confidence < LLM_MIN_CONFIDENCE:
            continue
        score = combine(candidate.cos, candidate.keyword, candidate.prior)
        level = classify(score)
        if level == "drop":
            continue
        if level == "auto":
            auto += 1
        else:
            pending += 1
        new_rows.append(
            NoteKp(
                note_id=note.id,
                kp_id=candidate.kp_id,
                confidence=Decimal(str(round(score, 3))),
                source="ai",
                confirmed=level == "auto",
            )
        )
    for row in old_rows:
        session.delete(row)
    for row in new_rows:
        session.add(row)
    session.flush()
    return AlignStats(
        candidates=len(candidates),
        matched=len(selected),
        auto=auto,
        pending=pending,
        dropped=len(candidates) - auto - pending,
    )


def list_pending(
    session: Session,
    *,
    viewer: User,
    params: PageParams,
    note_id: int | None = None,
) -> PageData[PendingAlignOut]:
    stmt = (
        select(NoteKp)
        .join(Note, NoteKp.note_id == Note.id)
        .where(
            NoteKp.source == "ai",
            NoteKp.confirmed.is_(False),
            NoteKp.confidence >= PENDING_THRESHOLD,
            NoteKp.confidence < AUTO_THRESHOLD,
            Note.user_id == viewer.id,
            Note.deleted_at.is_(None),
        )
    )
    if note_id is not None:
        stmt = stmt.where(NoteKp.note_id == note_id)
    stmt = stmt.order_by(NoteKp.note_id.desc(), NoteKp.kp_id)
    return paginate_query(session, stmt, params, item_model=PendingAlignOut)


def confirm_pairs(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> AlignBatchOut:
    rows = _owned_rows(session, viewer=viewer, pairs=pairs)
    confirmed = skipped = 0
    for pair in pairs:
        row = rows.get((pair.note_id, pair.kp_id))
        if row is None or row.confirmed:
            skipped += 1
            continue
        row.confirmed = True
        row.source = "manual"
        confirmed += 1
    session.commit()
    return AlignBatchOut(confirmed=confirmed, skipped=skipped)


def reject_pairs(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> AlignBatchOut:
    rows = _owned_rows(session, viewer=viewer, pairs=pairs)
    deleted = skipped = 0
    for pair in pairs:
        row = rows.get((pair.note_id, pair.kp_id))
        if row is None or row.confirmed or row.source != "ai":
            skipped += 1
            continue
        session.delete(row)
        deleted += 1
    session.commit()
    return AlignBatchOut(deleted=deleted, skipped=skipped)


def _owned_rows(
    session: Session, *, viewer: User, pairs: list[AlignPair]
) -> dict[tuple[int, int], NoteKp]:
    note_ids = {pair.note_id for pair in pairs}
    if not note_ids:
        raise InvalidParamError("items 不能为空")
    stmt = (
        select(NoteKp)
        .join(Note, NoteKp.note_id == Note.id)
        .where(
            NoteKp.note_id.in_(note_ids),
            Note.user_id == viewer.id,
            Note.deleted_at.is_(None),
        )
    )
    result: dict[tuple[int, int], NoteKp] = {}
    for row in session.scalars(stmt):
        note = row.note
        if note is None or note.user_id != viewer.id:
            continue
        result[(row.note_id, row.kp_id)] = row
    return result


def _note_text(note: Note) -> str:
    return f"{note.title}\n{note.content_text or ''}"


def _embedding_text(kp: KnowledgePoint, by_id: dict[int, KnowledgePoint]) -> str:
    path = " / ".join([*reversed(_ancestor_names(kp, by_id)), kp.name])
    return f"{path} {kp.description or ''}".strip()


def _ancestor_names(kp: KnowledgePoint, by_id: dict[int, KnowledgePoint]) -> list[str]:
    names: list[str] = []
    parent_id = kp.parent_id
    guard = 0
    while parent_id is not None and parent_id in by_id and guard < 10:
        parent = by_id[parent_id]
        names.append(parent.name)
        parent_id = parent.parent_id
        guard += 1
    return names


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    if norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / norm))