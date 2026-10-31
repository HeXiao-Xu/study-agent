"""S3-4 Prompt 版本服务：读取 active、创建不可变版本、激活。

Prompt 内容/渲染在 ai/rag；本层只做 DB 状态与版本规则。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.prompt_builder import PromptTemplateError
from app.core.exceptions import ConflictError, InvalidParamError, NotFoundError
from app.models.prompt_template import PromptTemplate

QA_PROMPT_NAME = "qa"
MAX_CONTENT_CHARS = 20000
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


def _clean_name(name: str) -> str:
    if not _NAME_RE.fullmatch(name):
        raise InvalidParamError("Prompt name 必须匹配 ^[a-z][a-z0-9_]{0,63}$")
    return name


def _clean_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version):
        raise InvalidParamError("Prompt version 必须匹配 ^[A-Za-z0-9._-]{1,32}$")
    return version


def _clean_content(content: str) -> str:
    clean = content.strip()
    if not clean:
        raise InvalidParamError("Prompt content 不能为空")
    if len(clean) > MAX_CONTENT_CHARS:
        raise InvalidParamError(f"Prompt content 不能超过 {MAX_CONTENT_CHARS} 字")
    return clean


def _clean_variables(variables: list[str] | None) -> list[str] | None:
    if variables is None:
        return None
    cleaned = [item.strip() for item in variables]
    if any(not item for item in cleaned):
        raise InvalidParamError("Prompt variables 不能包含空字符串")
    return cleaned


def _next_version(session: Session, name: str) -> str:
    versions = session.scalars(
        select(PromptTemplate.version).where(PromptTemplate.name == name)
    ).all()
    used = set(versions)
    numbers = [
        int(match.group(1))
        for version in used
        if (match := re.fullmatch(r"v(\d+)", version))
    ]
    candidate = max(numbers, default=0) + 1
    while f"v{candidate}" in used:
        candidate += 1
    return f"v{candidate}"


def get_active_prompt(
    session: Session, *, name: str = QA_PROMPT_NAME
) -> PromptTemplate:
    prompt = session.scalars(
        select(PromptTemplate).where(
            PromptTemplate.name == name,
            PromptTemplate.is_active.is_(True),
        )
    ).first()
    if prompt is None:
        raise PromptTemplateError(f"Prompt 未启用：{name}")
    return prompt


def list_prompts(
    session: Session, *, name: str | None = None
) -> list[PromptTemplate]:
    statement = select(PromptTemplate).order_by(
        PromptTemplate.created_at.desc(), PromptTemplate.id.desc()
    )
    if name is not None:
        statement = statement.where(PromptTemplate.name == _clean_name(name))
    return list(session.scalars(statement).all())


def create_prompt_version(
    session: Session,
    *,
    name: str,
    content: str,
    version: str | None = None,
    variables_json: list[str] | None = None,
    model_hint: str | None = None,
    created_by: int | None = None,
    activate: bool = False,
) -> PromptTemplate:
    clean_name = _clean_name(name)
    clean_content = _clean_content(content)
    clean_variables = _clean_variables(variables_json)
    clean_hint = model_hint.strip() if model_hint else None
    if clean_hint is not None and len(clean_hint) > 100:
        raise InvalidParamError("Prompt model_hint 不能超过 100 字")

    if version is None:
        clean_version = _next_version(session, clean_name)
    else:
        clean_version = _clean_version(version)
        exists = session.scalar(
            select(PromptTemplate.id).where(
                PromptTemplate.name == clean_name,
                PromptTemplate.version == clean_version,
            )
        )
        if exists is not None:
            raise ConflictError("Prompt 版本已存在")

    if activate:
        rows = session.scalars(
            select(PromptTemplate).where(PromptTemplate.name == clean_name)
        ).all()
        for row in rows:
            row.is_active = False

    prompt = PromptTemplate(
        name=clean_name,
        version=clean_version,
        content=clean_content,
        variables_json=clean_variables,
        model_hint=clean_hint,
        is_active=activate,
        created_by=created_by,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def activate_prompt(session: Session, prompt_id: int) -> PromptTemplate:
    target = session.get(PromptTemplate, prompt_id)
    if target is None:
        raise NotFoundError("Prompt 版本不存在")

    rows = session.scalars(
        select(PromptTemplate).where(PromptTemplate.name == target.name)
    ).all()
    for row in rows:
        row.is_active = row.id == target.id
    target.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(target)
    return target