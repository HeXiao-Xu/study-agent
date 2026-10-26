"""S2-6 文件名与类型规则。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import InvalidParamError
from app.services import file_service


def _settings(extensions: str = "pdf,docx,md,txt,png,jpg,jpeg", max_mb: int = 60):
    return SimpleNamespace(
        upload_allowed_extensions=extensions, upload_max_size_mb=max_mb
    )


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service, "get_settings", lambda: _settings())


def test_sanitize_filename_strips_path_traversal() -> None:
    assert file_service.sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_normalizes_backslashes() -> None:
    assert file_service.sanitize_filename(r"C:\Users\a\试卷.pdf") == "试卷.pdf"


def test_sanitize_filename_removes_control_chars() -> None:
    assert file_service.sanitize_filename("笔\x00记\n.md") == "笔记.md"


def test_sanitize_filename_truncates_but_keeps_extension() -> None:
    name = file_service.sanitize_filename("a" * 500 + ".pdf")
    assert len(name) == file_service.MAX_FILENAME_LENGTH
    assert name.endswith(".pdf")


def test_sanitize_filename_rejects_empty_and_dots() -> None:
    for bad in ("", "   ", ".", "..", "/", "\\\\"):
        with pytest.raises(InvalidParamError):
            file_service.sanitize_filename(bad)


def test_detect_type_is_case_insensitive() -> None:
    assert file_service.detect_type("A.PDF") == ("pdf", "application/pdf")


def test_detect_type_rejects_unknown_extension() -> None:
    with pytest.raises(InvalidParamError) as excinfo:
        file_service.detect_type("run.exe")
    assert "pdf" in excinfo.value.message


def test_detect_type_follows_configured_whitelist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_service, "get_settings", lambda: _settings("pdf"))
    with pytest.raises(InvalidParamError):
        file_service.detect_type("note.md")


def test_check_magic_rejects_text_disguised_as_pdf() -> None:
    with pytest.raises(InvalidParamError):
        file_service.check_magic(b"not a pdf at all", "pdf")


def test_check_magic_accepts_png_signature() -> None:
    file_service.check_magic(b"\x89PNG\r\n\x1a\n" + b"rest", "png")


def test_check_magic_rejects_binary_text_file() -> None:
    with pytest.raises(InvalidParamError):
        file_service.check_magic(b"abc\x00def", "txt")


def test_check_magic_accepts_docx_zip_header() -> None:
    file_service.check_magic(b"PK\x03\x04rest", "docx")


def test_allowed_extensions_reads_config() -> None:
    assert file_service.allowed_extensions() == [
        "pdf",
        "docx",
        "md",
        "txt",
        "png",
        "jpg",
        "jpeg",
    ]