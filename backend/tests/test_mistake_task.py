"""S4-2 拍照错题任务：建题→建错题、复用、作答优先级、失败不吞、不 commit。"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.ai.vision import VisionExtract
from app.core.exceptions import ForbiddenError, InvalidParamError, NotFoundError
from app.models.enums import MistakeStatus
from app.models.mistake import Mistake
from app.models.question import Question
from app.services import mistake_service, task_service
from app.tasks import mistake_recognize as task_module


class FakeSession:
    def __init__(self, *, objects=None, scalar_results=None) -> None:
        self.objects = objects or {}
        self.scalar_results = list(scalar_results or [])
        self.added: list[object] = []
        self._pending: list[object] = []
        self._next_id = 900
        self.flushes = 0
        self.commits = 0

    def get(self, entity, pk):
        return self.objects.get((entity, pk))

    def scalar(self, statement):
        return self.scalar_results.pop(0) if self.scalar_results else None

    def add(self, instance) -> None:
        # 模拟 SQLAlchemy：add 只登记待插入，主键在 flush 时才分配。
        # 若这里直接给 id，会让「handler 忘记 flush → mistake_id=None」的 C1 被测试掩盖。
        self._pending.append(instance)
        self.added.append(instance)

    def flush(self) -> None:
        self.flushes += 1
        for instance in self._pending:
            if getattr(instance, "id", None) is None:
                self._next_id += 1
                instance.id = self._next_id
        self._pending.clear()

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


class FakeUpload:
    def __init__(self, filename: str = "photo.png") -> None:
        self.filename = filename


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
    assert result["warnings"] == []
    assert result["mistake_id"] is not None
    assert result["mistake_id"] == session.added[0].id
    assert session.flushes >= 1  # C1：新建错题必须 flush 才能拿到 id
    assert session.commits == 0  # handler 不 commit（runner 统一提交）
    assert patched["origin"] == "upload"
    assert patched["source_file_id"] == 41
    assert isinstance(session.added[0], Mistake)


def test_fake_session_assigns_id_only_on_flush():
    """反向契约：没有 flush 就取 id 会拿到 None，防止 FakeSession 再次掩盖 C1。"""
    session = FakeSession()
    mistake = Mistake(
        user_id=1, question_id=65, status=MistakeStatus.TODO.value, correct_streak=0
    )
    session.add(mistake)
    assert mistake.id is None
    session.flush()
    assert mistake.id is not None


def test_task_prefers_student_answer_over_vision(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload(my_answer_md="我自己写的"))
    assert result["used_answer_source"] == "student"
    assert session.added[0].my_answer_md == "我自己写的"


def test_task_marks_low_confidence(monkeypatch, patched):
    monkeypatch.setattr(
        task_module, "extract_mistake",
        lambda *a, **kw: _vision(confidence=0.3, warnings=["作答无法辨认"]),
    )
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["low_confidence"] is True
    assert result["warnings"] == ["作答无法辨认"]


def test_task_confidence_at_threshold_is_not_low(monkeypatch, patched):
    monkeypatch.setattr(
        task_module, "extract_mistake",
        lambda *a, **kw: _vision(confidence=0.5),
    )
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])
    result = task_module.mistake_recognize_task(session, _payload())
    assert result["low_confidence"] is False


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


def test_task_enqueues_analysis_best_effort(monkeypatch, patched):
    """S4-3：识别成功后 best-effort 入队诊断，失败也不影响识别结果。"""
    enqueued: list[int] = []
    monkeypatch.setattr(
        task_module.mistake_analysis_service,
        "safe_enqueue",
        lambda session, *, owner, mistake_id, queue: enqueued.append(mistake_id) or True,
    )
    monkeypatch.setattr(task_module, "get_task_queue", lambda: "fake-queue")
    owner = type("U", (), {"id": 1})()
    session = FakeSession(
        objects={(task_module.File, 41): FakeFile(), (task_module.User, 1): owner},
        scalar_results=[None],
    )

    result = task_module.mistake_recognize_task(session, _payload())

    assert result["analysis_enqueued"] is True
    assert enqueued == [result["mistake_id"]]


def test_task_marks_analysis_not_enqueued_without_owner(patched):
    session = FakeSession(objects={(task_module.File, 41): FakeFile()}, scalar_results=[None])

    result = task_module.mistake_recognize_task(session, _payload())

    assert result["analysis_enqueued"] is False


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
    assert session.flushes == 0  # 复用路径 id 已存在，不需要再 flush
    assert session.added == []
    assert existing.status == MistakeStatus.TODO.value
    assert existing.correct_streak == 0
    assert existing.my_answer_md == "对称轴 x=2"
    # D-1：录入不是复习，复用重置不改 last_review_at；答案缺省时不覆盖旧值。
    assert existing.last_review_at == reviewed_at
    assert existing.correct_answer_md == "旧答案"
    assert existing.image_file_id == 41


def _fake_task(task_id: int = 98):
    return type("Task", (), {"id": task_id, "name": "mistake.recognize", "status": "pending"})()


def _patch_upload(monkeypatch, *, mime: str = "image/png"):
    def fake_upload_file(session, *, owner, upload, storage, parse):
        return type("F", (), {"id": 41, "mime": mime})(), False

    monkeypatch.setattr(mistake_service.file_service, "upload_file", fake_upload_file)


def _patch_subject(monkeypatch, *, calls: list[int] | None = None):
    def fake_ensure_subject_exists(session, subject_id):
        if calls is not None:
            calls.append(subject_id)

    monkeypatch.setattr(
        mistake_service.question_service, "ensure_subject_exists", fake_ensure_subject_exists
    )


def test_start_photo_recognize_uploads_and_enqueues(monkeypatch):
    captured = {}
    subject_calls: list[int] = []

    def fake_create_task(session, *, owner, name, payload, queue):
        captured.update({"name": name, "payload": payload})
        return _fake_task()

    monkeypatch.setattr(task_service, "create_task", fake_create_task)
    _patch_upload(monkeypatch)
    _patch_subject(monkeypatch, calls=subject_calls)
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    task = mistake_service.start_photo_recognize(
        session, owner=owner, subject_id=7, upload=FakeUpload(), storage=object(), queue=object()
    )
    assert subject_calls == [7]
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
        return _fake_task(99)

    monkeypatch.setattr(task_service, "create_task", fake_create_task)
    _patch_upload(monkeypatch)
    _patch_subject(monkeypatch)
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    mistake_service.start_photo_recognize(
        session, owner=owner, subject_id=7, upload=FakeUpload(), storage=object(),
        queue=object(), my_answer_md="手填作答",
    )
    assert captured["payload"]["my_answer_md"] == "手填作答"


def test_start_photo_recognize_missing_subject_does_not_upload(monkeypatch):
    def fake_ensure_subject_exists(session, subject_id):
        raise NotFoundError("学科不存在")

    def fail_upload(*args, **kwargs):
        raise AssertionError("学科不存在时不应落库")

    def fail_create_task(*args, **kwargs):
        raise AssertionError("学科不存在时不应入队")

    monkeypatch.setattr(
        mistake_service.question_service, "ensure_subject_exists", fake_ensure_subject_exists
    )
    monkeypatch.setattr(mistake_service.file_service, "upload_file", fail_upload)
    monkeypatch.setattr(task_service, "create_task", fail_create_task)
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    with pytest.raises(NotFoundError):
        mistake_service.start_photo_recognize(
            session, owner=owner, subject_id=404, upload=FakeUpload(), storage=object(), queue=object()
        )


def test_start_photo_recognize_rejects_pdf_before_upload(monkeypatch):
    def fail_upload(*args, **kwargs):
        raise AssertionError("非图片不应落库")

    monkeypatch.setattr(mistake_service.file_service, "upload_file", fail_upload)
    _patch_subject(monkeypatch)
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    with pytest.raises(InvalidParamError):
        mistake_service.start_photo_recognize(
            session, owner=owner, subject_id=7, upload=FakeUpload("题目.pdf"),
            storage=object(), queue=object(),
        )
    # I4：WebP 未在上传层开放，口径收窄为 PNG/JPEG。
    assert mistake_service.IMAGE_MIMES == {"image/png", "image/jpeg"}


def test_start_photo_recognize_rejects_record_mime_mismatch(monkeypatch):
    def fail_create_task(*args, **kwargs):
        raise AssertionError("magic 与扩展名不一致时不应入队")

    monkeypatch.setattr(task_service, "create_task", fail_create_task)
    _patch_upload(monkeypatch, mime="application/pdf")
    _patch_subject(monkeypatch)
    session = FakeSession()
    owner = type("U", (), {"id": 1})()
    with pytest.raises(InvalidParamError):
        mistake_service.start_photo_recognize(
            session, owner=owner, subject_id=7, upload=FakeUpload(), storage=object(), queue=object()
        )
