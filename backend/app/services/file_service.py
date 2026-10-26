"""S2-6 文件上传服务（spec §7）。

文件名只做展示：对象键用内容哈希，路径穿越在源头就被砍掉。
类型靠「扩展名白名单 + 文件头 magic」双校验：只信扩展名会被改名绕过。
"""
from __future__ import annotations

import re

from app.core.config import get_settings
from app.core.exceptions import InvalidParamError

MAX_FILENAME_LENGTH = 200

# ext -> (mime, magic)；magic=None 表示文本类，仅拒绝 NUL
TYPE_TABLE: dict[str, tuple[str, bytes | None]] = {
    "pdf": ("application/pdf", b"%PDF-"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK\x03\x04",
    ),
    "md": ("text/markdown", None),
    "txt": ("text/plain", None),
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def allowed_extensions() -> list[str]:
    raw = get_settings().upload_allowed_extensions
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def sanitize_filename(name: str | None) -> str:
    raw = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _CONTROL.sub("", raw).strip().strip(".")
    if not cleaned or cleaned in {".", ".."}:
        raise InvalidParamError("文件名不合法")
    if len(cleaned) > MAX_FILENAME_LENGTH:
        stem, _, ext = cleaned.rpartition(".")
        if not ext or len(ext) > 20:
            stem, ext = cleaned, ""
        keep = MAX_FILENAME_LENGTH - (len(ext) + 1 if ext else 0)
        cleaned = (stem[:keep] + f".{ext}") if ext else stem[:keep]
    return cleaned


def detect_type(filename: str) -> tuple[str, str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = allowed_extensions()
    if ext not in allowed or ext not in TYPE_TABLE:
        shown = "，".join(allowed) if allowed else "（未配置）"
        raise InvalidParamError(
            f"不支持的文件类型：{ext or '（无扩展名）'}（允许：{shown}）"
        )
    return ext, TYPE_TABLE[ext][0]


def check_magic(head: bytes, ext: str) -> None:
    _, magic = TYPE_TABLE[ext]
    if magic is None:
        if b"\x00" in head[:4096]:
            raise InvalidParamError("文件内容与类型不符")
        return
    if not head.startswith(magic):
        raise InvalidParamError("文件内容与类型不符")