"""S4-1 切题任务：部分成功、幂等、扫描件与越权失败路径。"""
from __future__ import annotations

import json

import pytest

from app.ai.align.scoring import cosine
from app.ai.extract import ExtractedQuestion, ExtractResult
from app.ai.extract.question_extractor import QuestionExtractError, extract_questions
from app.ai.llm import LLMResponse
from app.ai.parse.models import ParsedDocument
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.models.file import File
from app.models.question import Question
from app.models.subject import Subject
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
    """每个文本一个 one-hot 向量：不同题干向量正交，只有同题才重合。"""

    dim = 20
    model = "fake-embed"

    def encode(self, texts, *, on_batch=None):
        vectors = []
        for index, _ in enumerate(texts):
            vector = [0.0] * self.dim
            vector[index % self.dim] = 1.0
            vectors.append(vector)
        return vectors


class FakeLLM:
    def __init__(self, text: str) -> None:
        self.text = text
        self.max_tokens: list[int | None] = []

    def chat(self, messages, *, temperature=None, max_tokens=None, scene="qa"):
        self.max_tokens.append(max_tokens)
        return LLMResponse(text=self.text, model="fake-llm", total_tokens=10)


class FakeStorage:
    def download_to(self, key: str, handle) -> None:
        handle.write(b"%PDF-1.4 fake")


def _two_gate_check(session, *, subject_id, stem_hash, vec=None, **kwargs):
    """在内存里复用真实判重语义：先哈希、再余弦阈值。"""
    for obj in session.added:
        if not isinstance(obj, Question) or obj.subject_id != subject_id:
            continue
        if obj.stem_hash == stem_hash:
            return obj
        if vec and obj.embedding is not None:
            threshold = question_service.DUPLICATE_COS_THRESHOLD
            if cosine(vec, list(obj.embedding)) >= threshold:
                return obj
    return None


def _file(file_id: int = 7, owner: int = 1, name: str = "试卷.pdf") -> File:
    record = File(user_id=owner, filename=name, mime="application/pdf", size=10,
                  sha256="a" * 64, storage_path="uploads/1/x.pdf", parse_status="done")
    record.id = file_id
    return record


def _subject(name: str = "高中物理", subject_id: int = 1) -> Subject:
    record = Subject(name=name, code="physics", stage="高中")
    record.id = subject_id
    return record


def _extracted(stem: str = "已知函数 $f(x)=x$，求 $f(1)$。") -> ExtractedQuestion:
    return ExtractedQuestion(
        stem_md=stem, qtype="解答", difficulty=2, answer_md="1", answer_source="paper"
    )


def _payload(**overrides):
    payload = {"file_id": 7, "subject_id": 1, "origin": "upload", "created_by": 1}
    payload.update(overrides)
    return payload


def _fake_extract_distinct(**kwargs):
    """按 block 的题号回不同的题干：20 道题的哈希与向量都不同。"""
    number = kwargs["question_text"].split(".", 1)[0].strip()
    return ExtractResult(
        questions=[_extracted(f"第{number}题：已知函数 $f(x)=x+{number}$，求 $f(1)$。")]
    )


TWENTY = "\n".join(
    ["一、选择题（本题共 20 小题）"] + [f"{index}. 第{index}题题干内容" for index in range(1, 21)]
)


def test_creates_all_questions(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return _fake_extract_distinct(**kwargs)

    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(question_extract, "extract_questions", fake_extract)
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    monkeypatch.setattr(question_service, "check_duplicate", _two_gate_check)
    session = FakeSession(objects={(File, 7): _file(), (Subject, 1): _subject()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["detected_count"] == 20
    assert result["created"] == 20
    assert result["duplicated"] == 0
    assert result["failed_items"] == []
    assert session.commits == 0  # 由 runner 统一提交
    assert {call["subject_name"] for call in calls} == {"高中物理"}


def test_same_stem_blocks_are_duplicated(monkeypatch, caplog) -> None:
    calls: list[dict] = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return ExtractResult(questions=[_extracted()])

    monkeypatch.setattr(question_extract, "_load_text", lambda file: TWENTY)
    monkeypatch.setattr(question_extract, "extract_questions", fake_extract)
    monkeypatch.setattr(question_extract, "get_embedding_client", lambda: FakeEmbedder())
    monkeypatch.setattr(question_service, "check_duplicate", _two_gate_check)
    session = FakeSession(objects={(File, 7): _file()})
    result = question_extract.question_extract_task(session, _payload())
    assert result["created"] == 1
    assert result["duplicated"] == 19
    assert sum(isinstance(obj, Question) for obj in session.added) == 1
    # 学科查不到时回退默认名，任务不因此失败，但要留下可排查的 WARNING
    assert {call["subject_name"] for call in calls} == {"高中数学"}
    assert any(
        record.getMessage() == "question_extract_subject_missing" for record in caplog.records
    )


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


def test_block_mode_token_budget_scales_with_question_count() -> None:
    payload = json.dumps({"questions": [_extracted().model_dump()]}, ensure_ascii=False)
    block_client = FakeLLM(payload)
    extract_questions(
        question_text="整卷原文", mode="block", expected_count=20, llm_client=block_client
    )
    assert block_client.max_tokens == [8000]

    single_client = FakeLLM(payload)
    extract_questions(question_text="1. 已知函数", llm_client=single_client)
    assert single_client.max_tokens == [1500]