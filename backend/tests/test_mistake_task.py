"""S4-2 拍照错题任务：建题→建错题、复用、作答优先级、失败不吞、不 commit。"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.ai.vision import VisionExtract
from app.core.exceptions import ForbiddenError, InvalidParamError
from app.models.enums import MistakeStatus
from app.models.mistake import Mistake
from app.models.question import Question
from app.services import mistake_service
from app.tasks import mistake_recognize as task_module


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.added: list[object] = []
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def add(self, instance) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = 900
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class FakeStorage:
    def download_to(self, key: str, target: BytesIO) -> None:
        target.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)


class FakeFile:
    def __init__(self) -> None:
        self.id = 41
        self.user_id = 1
        self.mime = "image/png"
        self.filename = "photo.png"
        self.storage_path = "obj/41"


class FakeEmbedder:
    dim = 2
    model = "fake-embed"

    def encode(self, texts, *, on_batch=None):
        return [[0.1, 0.9] for _ in texts]


def _vision(**overrides) -> VisionExtract:
    payload = {
        "stem_md": "已知函数 $f(x)=x^{2}-4x+3$，求对称轴。",
        "options": None,
        "qtype": "解答",
        "correct_answer_md": None,
        "my_answer_md": "对称轴 x=2",
        "confidence": 0.9,
        "warnings": [],
    }
    payload.update(overrides)
    return VisionExtract.model_validate(payload)


@pytest.fixture()
def patched(monkeypatch):
    calls = {}

    def fake_extract(image_bytes, mime, *, subject_name, llm_client=None):
        calls["subject_name"] = subject_name
        calls["mime"] = mime
        return _vision()

    def fake_create_extracted(session, *, extracted, subject_id, origin, created_by,
                             source_file_id, vec):
        calls["extracted_stem"] = extracted.stem_md
        calls["origin"] = origin
        calls["source_file_id"] = source_file_id
        question = Question(
            subject_id=subject_id, stem_md=extracted.stem_md, stem_hash="h-photo",
            qtype=extracted.qtype, difficulty=extracted.difficulty, origin=origin,
            answer_md=extracted.answer_md, verified=True,
        )
        question.id = 65
        return question, False

    monkeypatch.setattr(task_module, "extract_mistake", fake_extract)
    monkeypatch.setattr(task_module.question_service, "create_extracted_question", fake_create_extracted)
    monkeypatch.setattr(task_module, "get_embedding_client", lambda: FakeEmbedder())
    monkeypatch.setattr(task_module, "get_storage", lambda: FakeStorage())
    return calls


def _payload(**overrides) -> dict:
    payload = {"file_id": 41, "subject_id": 7, "user_id": 1, "my_answer_md": None}
    payload.update(overrides)
    return payload


def test_task_creates_question_and_mistake(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["question_id"] == 65
    assert result["created"] is True
    assert result["reused_question"] is False
    assert result["low_confidence"] is False
    assert session.commits == 0  # handler 不 commit（runner 统一提交）
    assert patched["origin"] == "upload"
    assert patched["source_file_id"] == 41
    assert isinstance(session.added[0], Mistake)


def test_task_prefers_student_answer_over_vision(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload(my_answer_md="我自己写的"))
    assert result["used_answer_source"] == "student"
    assert session.added[0].my_answer_md == "我自己写的"


def test_task_marks_low_confidence(monkeypatch, patched):
    monkeypatch.setattr(
        task_module, "extract_mistake",
        lambda *a, **kw: _vision(confidence=0.3),
    )
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["low_confidence"] is True


def test_task_rejects_missing_file():
    session = FakeSession(objects={})
    with pytest.raises(InvalidParamError):
        task_module.mistake_recognize_task(session, _payload())


def test_task_rejects_foreign_file():
    file = FakeFile()
    file.user_id = 2
    session = FakeSession(objects={(task_module.File, 41): file})
    with pytest.raises(ForbiddenError):
        task_module.mistake_recognize_task(session, _payload())


def test_task_rejects_non_image_file(patched):
    file = FakeFile()
    file.mime = "application/pdf"
    session = FakeSession(objects={(task_module.File, 41): file})
    with pytest.raises(InvalidParamError):
        task_module.mistake_recognize_task(session, _payload())


def test_task_reuses_existing_mistake_without_commit(patched):
    reviewed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    existing = Mistake(
        user_id=1, question_id=65, status=MistakeStatus.MASTERED.value, correct_streak=2,
        my_answer_md="旧作答", correct_answer_md="旧答案", last_review_at=reviewed_at,
    )
    existing.id = 12
    session = FakeSession(
        objects={(task_module.File, 41): FakeFile()}, scalar_results=[existing]
    )
    result = task_module.mistake_recognize_task(session, _payload())

    assert result["created"] is False
    assert result["mistake_id"] == 12
    assert session.commits == 0
    assert session.added == []
    assert existing.status == MistakeStatus.TODO.value
    assert existing.correct_streak == 0
    assert existing.my_answer_md == "对称轴 x=2"
    # D-1：录入不是复习，复用重置不改 last_review_at；答案缺省时不覆盖旧值。
    assert existing.last_review_at == reviewed_at
    assert existing.correct_answer_md == "旧答案"
    assert existing.image_file_id == 41


def test_start_photo_recognize_uploads_and_enqueues(monkeypatch):
    captured = {}

    class FakeQueue:
        pass

    def fake_create_task(session, *, owner, name, payload, queue):
        captured.update({"name": name, "payload": payload})
        return type("Task", (), {"id": 98, "name": name, "status": "pending"})()

    monkeypatch.setattr(mistake_service.task_service, "create_task", fake_create_task)
    monkeypatch.setattr(
        mistake_service.file_service, "upload_file",
        lambda session, *, owner, upload, storage, parse: (type("F", (), {"id": 41, "mime": "image/png"})(), False),
    )
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    task = mistake_service.start_photo_recognize(
        session, owner=owner, subject_id=7, upload=object(), storage=object(), queue=FakeQueue()
    )
    assert captured["name"] == "mistake.recognize"
    assert captured["payload"]["file_id"] == 41
    assert captured["payload"]["user_id"] == 1
    assert captured["payload"]["subject_id"] == 7
    assert "my_answer_md" in captured["payload"]
    assert task.id == 98


def test_start_photo_recognize_passes_student_answer(monkeypatch):
    captured = {}

    def fake_create_task(session, *, owner, name, payload, queue):
        captured["payload"] = payload
        return type("Task", (), {"id": 99})()

    monkeypatch.setattr(mistake_service.task_service, "create_task", fake_create_task)
    monkeypatch.setattr(
        mistake_service.file_service, "upload_file",
        lambda session, *, owner, upload, storage, parse: (type("F", (), {"id": 41, "mime": "image/png"})(), False),
    )
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    mistake_service.start_photo_recognize(
        session, owner=owner, subject_id=7, upload=object(), storage=object(),
        queue=object(), my_answer_md="手填作答",
    )
    assert captured["payload"]["my_answer_md"] == "手填作答"


def test_start_photo_recognize_rejects_non_image(monkeypatch):
    def fake_create_task(*args, **kwargs):
        raise AssertionError("非图片不应入队")

    monkeypatch.setattr(mistake_service.task_service, "create_task", fake_create_task)
    monkeypatch.setattr(
        mistake_service.file_service, "upload_file",
        lambda session, *, owner, upload, storage, parse: (
            type("F", (), {"id": 41, "mime": "application/pdf"})(), False
        ),
    )
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    with pytest.raises(InvalidParamError):
        mistake_service.start_photo_recognize(
            session, owner=owner, subject_id=7, upload=object(), storage=object(), queue=object()
        )