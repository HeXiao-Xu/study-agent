"""S4-1 切题任务：部分成功、幂等、扫描件与越权失败路径。"""
from __future__ import annotations

import pytest

from app.ai.extract import ExtractedQuestion, ExtractResult
from app.ai.extract.question_extractor import QuestionExtractError
from app.ai.parse.models import ParsedBlock, ParsedDocument
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.models.file import File
from app.models.question import Question
from app.services import question_service
from app.tasks import question_extract


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None, scalars_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0
        self._next_id = 500

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, statement):
        return self.scalars_results.pop(0) if self.scalars_results else []

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            self._next_id += 1
            instance.id = self._next_id
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def delete(self, instance) -> None:
        self.deleted.append(instance)

    def commit(self) -> None:
        self.commits += 1


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def encode(self, texts, *, on_batch=None):
        return [[1.0, 0.0] for _ in texts]


class FakeStorage:
    def download_to(self, key: str, handle) -> None:
        handle.write(b"%PDF-1.4 fake")


def _file(file_id: int = 7, owner: int = 1, name: str = "试卷.pdf") -> File:
    record = File(user_id=owner, filename=name, mime="application/pdf", size=10,
                  sha256="a" * 64, storage_path="uploads/1/x.pdf", parse_status="done")
    record.id = file_id
    return record


def _extracted(stem: str = "已知函数 $f(x)=x$，求 $f(1)$。") -> ExtractedQuestion:
    return ExtractedQuestion(
        stem_md=stem, qtype="解答", difficulty=2, answer_md="1", answer_source="paper"
    )


def _payload(**overrides):
    payload = {"file_id": 7, "subject_id": 1, "origin": "upload", "created_by": 1}
    payload.update(overrides)
    return payload


TWENTY = "\n".join(
    ["一、选择题（本题共 20 小题）"] + [f"{index}. 第{index}题题干内容" for index in range(1, 21)]
)


def test_creates_all_questions(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(
        question_extract, "extract_questions", lambda **kwargs: ExtractResult(questions=[_extracted()])
    )
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["detected_count"] == 20
    assert result["created"] == 20
    assert result["duplicated"] == 0
    assert result["failed_items"] == []
    assert session.commits == 0  # 由 runner 统一提交


def test_reimport_marks_all_duplicated(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(
        question_extract, "extract_questions", lambda **kwargs: ExtractResult(questions=[_extracted()])
    )
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    existing = Question(subject_id=1, stem_md="已知函数", stem_hash="dup", qtype="解答", difficulty=2)
    existing.id = 99
    monkeypatch.setattr(question_service, "check_duplicate", lambda *args, **kwargs: existing)
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["created"] == 0
    assert result["duplicated"] == 20


def test_single_block_failure_is_reported(monkeypatch) -> None:
    text = "\n".join(
        ["一、选择题（本题共 3 小题）", "1. 坏题", "2. 好题甲", "3. 好题乙"]
    )
    monkeypatch.setattr(question_extract, "_load_text", lambda file: text)

    def fake_extract(**kwargs):
        if "坏题" in kwargs["question_text"]:
            raise QuestionExtractError("校验失败：选择题选项少于 2 项")
        return ExtractResult(questions=[_extracted()])

    monkeypatch.setattr(question_extract, "extract_questions", fake_extract)
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["created"] == 2
    assert [item["index"] for item in result["failed_items"]] == [1]
    assert "选项少于" in result["failed_items"][0]["reason"]


def test_scanned_pdf_fails(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        question_extract,
        "parse_document",
        lambda path: ParsedDocument(
            source=str(path), parser="pymupdf", is_scanned=True, degraded_reason="无文本", blocks=[]
        ),
    )
    session = FakeSession(objects={(File, 7): _file()})
    with pytest.raises(InvalidParamError) as excinfo:
        question_extract.question_extract_task(session, _payload())
    assert "扫描" in str(excinfo.value)


def test_file_owner_mismatch_fails() -> None:
    session = FakeSession(objects={(File, 7): _file(owner=2)})
    with pytest.raises(ForbiddenError):
        question_extract.question_extract_task(session, _payload(created_by=1))


def test_no_question_text_fails(monkeypatch) -> None:
    monkeypatch.setattr(question_extract, "_load_text", lambda file: "没有任何题号的说明文字")
    session = FakeSession(objects={(File, 7): _file()})
    with pytest.raises(InvalidParamError):
        question_extract.question_extract_task(session, _payload())