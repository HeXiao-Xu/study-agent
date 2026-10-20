"""S1-6 上下文组装 + Prompt 渲染。

预算按 tiktoken cl100k_base 计；排序只认 rerank 分，没有分数时保持输入顺序。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tiktoken
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.ai.rag.retriever import RetrievedChunk

CONTEXT_MAX_TOKENS = 4000
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
PROMPT_PATH = _PROMPT_DIR / "qa_v1.md"


class PromptTemplateError(RuntimeError):
    """模板缺失或渲染失败；不携带上下文正文。"""


@dataclass(frozen=True)
class Citation:
    index: int
    note_id: int
    chunk_id: int
    source_file_id: int | None
    heading_path: str | None
    page_no: int | None
    snippet: str
    rerank_score: float | None


@dataclass(frozen=True)
class ContextItem:
    citation: Citation
    content: str
    tokens: int


@dataclass(frozen=True)
class BuiltContext:
    text: str
    items: list[ContextItem]
    tokens: int
    truncated: bool


_encoding: tiktoken.Encoding | None = None


def _encoder() -> tiktoken.Encoding:
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def _format_header(citation: Citation) -> str:
    source = (
        f"文件 #{citation.source_file_id}"
        if citation.source_file_id is not None
        else "文件未知"
    )
    page = (
        f"第 {citation.page_no} 页"
        if citation.page_no is not None
        else "页码未知"
    )
    heading = citation.heading_path or "章节未标注"
    return (
        f"[{citation.index}] 来源：笔记 #{citation.note_id} / {source} / "
        f"{page} / 章节：{heading}\n"
    )


def build_context(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int = CONTEXT_MAX_TOKENS,
) -> BuiltContext:
    if max_tokens <= 0:
        raise ValueError("max_tokens 必须为正整数")

    indexed = list(enumerate(chunks))
    indexed.sort(
        key=lambda pair: (
            pair[1].rerank_score is None,
            -(pair[1].rerank_score or 0.0),
            pair[0],
        )
    )
    ordered: list[RetrievedChunk] = []
    seen: set[int] = set()
    for _, chunk in indexed:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        ordered.append(chunk)

    enc = _encoder()
    parts: list[str] = []
    items: list[ContextItem] = []
    used = 0
    truncated = False

    for chunk in ordered:
        index = len(items) + 1
        prefix = "" if not parts else "\n\n"
        placeholder = Citation(
            index=index,
            note_id=chunk.note_id,
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            heading_path=chunk.heading_path,
            page_no=chunk.page_no,
            snippet="",
            rerank_score=chunk.rerank_score,
        )
        header = _format_header(placeholder)
        header_tokens = len(enc.encode(prefix + header))
        if used + header_tokens >= max_tokens:
            truncated = True
            break

        body_tokens = enc.encode(chunk.content)
        available = max_tokens - used - header_tokens
        if len(body_tokens) <= available:
            content = chunk.content
        else:
            lo, hi = 0, min(len(body_tokens), available)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                candidate = enc.decode(body_tokens[:mid])
                if len(enc.encode(prefix + header + candidate)) <= max_tokens - used:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                truncated = True
                break
            content = enc.decode(body_tokens[:lo])
            truncated = True

        citation = Citation(
            index=index,
            note_id=chunk.note_id,
            chunk_id=chunk.chunk_id,
            source_file_id=chunk.source_file_id,
            heading_path=chunk.heading_path,
            page_no=chunk.page_no,
            snippet=content[:200],
            rerank_score=chunk.rerank_score,
        )
        item_text = prefix + _format_header(citation) + content
        item_tokens = len(enc.encode(item_text))
        if used + item_tokens > max_tokens:
            truncated = True
            break
        parts.append(item_text)
        items.append(ContextItem(citation=citation, content=content, tokens=item_tokens))
        used += item_tokens
        if truncated:
            break

    text = "".join(parts)
    return BuiltContext(
        text=text,
        items=items,
        tokens=len(enc.encode(text)) if text else 0,
        truncated=truncated,
    )


def render_prompt(
    context: str,
    question: str,
    *,
    template_path: Path | None = None,
) -> str:
    path = PROMPT_PATH if template_path is None else template_path
    if not path.is_file():
        raise PromptTemplateError(f"Prompt 模板不存在：{path}")
    env = Environment(
        loader=FileSystemLoader(str(path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    try:
        template = env.get_template(path.name)
        return template.render(context=context, question=question)
    except Exception as exc:  # Jinja2 的 TemplateNotFound/UndefinedError 统一收口
        raise PromptTemplateError(f"Prompt 模板渲染失败：{path}") from exc