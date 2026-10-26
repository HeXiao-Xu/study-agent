"""S2-6 对象存储适配器：注入假 MinIO 客户端，不连网络。"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from minio.error import S3Error

from app.core import storage as storage_module
from app.core.exceptions import StorageUnavailableError
from app.core.storage import MinioStorage, get_storage


class FakeStat:
    def __init__(self, size: int) -> None:
        self.size = size


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.closed = False
        self.released = False

    def stream(self, size: int):
        for start in range(0, len(self._payload), size):
            yield self._payload[start : start + size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.buckets: set[str] = set()
        self.puts: list[dict[str, object]] = []
        self.removed: list[str] = []
        self.bucket_checks = 0
        self.made: list[str] = []
        self.fail_put = False

    def bucket_exists(self, bucket: str) -> bool:
        self.bucket_checks += 1
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.buckets.add(bucket)
        self.made.append(bucket)

    def put_object(self, bucket, key, data, length, content_type):  # noqa: ANN001
        if self.fail_put:
            raise OSError("boom")
        self.puts.append(
            {"bucket": bucket, "key": key, "size": length, "content_type": content_type}
        )
        self.objects[key] = data.read()

    def stat_object(self, bucket, key):  # noqa: ANN001
        if key not in self.objects:
            raise S3Error(
                response=None,
                code="NoSuchKey",
                message="missing",
                resource=key,
                request_id="req",
                host_id="host",
            )
        return FakeStat(len(self.objects[key]))

    def remove_object(self, bucket, key):  # noqa: ANN001
        self.removed.append(key)
        self.objects.pop(key, None)

    def get_object(self, bucket, key):  # noqa: ANN001
        return FakeResponse(self.objects[key])

    def presigned_get_object(self, bucket, key, expires=None):  # noqa: ANN001
        return f"http://minio/{bucket}/{key}?expires={int(expires.total_seconds())}"


def test_put_sends_length_and_content_type() -> None:
    client = FakeMinio()
    store = MinioStorage(client=client, bucket="b")
    store.put("k.pdf", BytesIO(b"%PDF-1.4"), size=8, content_type="application/pdf")
    assert client.puts == [
        {"bucket": "b", "key": "k.pdf", "size": 8, "content_type": "application/pdf"}
    ]


def test_put_creates_missing_bucket_once() -> None:
    client = FakeMinio()
    store = MinioStorage(client=client, bucket="b")
    store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    store.put("b", BytesIO(b"y"), size=1, content_type="text/plain")
    assert client.made == ["b"]
    assert client.bucket_checks == 1


def test_put_skips_bucket_creation_when_exists() -> None:
    client = FakeMinio()
    client.buckets.add("b")
    store = MinioStorage(client=client, bucket="b")
    store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    assert client.made == []


def test_put_wraps_sdk_failure() -> None:
    client = FakeMinio()
    client.fail_put = True
    store = MinioStorage(client=client, bucket="b")
    with pytest.raises(StorageUnavailableError) as excinfo:
        store.put("a", BytesIO(b"x"), size=1, content_type="text/plain")
    assert excinfo.value.code == 50000
    assert "minio" not in excinfo.value.message.lower()


def test_delete_removes_key() -> None:
    client = FakeMinio()
    client.objects["a"] = b"x"
    MinioStorage(client=client, bucket="b").delete("a")
    assert client.removed == ["a"]


def test_exists_reports_true_and_false() -> None:
    client = FakeMinio()
    client.objects["a"] = b"x"
    store = MinioStorage(client=client, bucket="b")
    assert store.exists("a") is True
    assert store.exists("missing") is False


def test_download_to_writes_target_stream() -> None:
    client = FakeMinio()
    client.objects["a"] = b"hello"
    target = BytesIO()
    MinioStorage(client=client, bucket="b").download_to("a", target)
    assert target.getvalue() == b"hello"


def test_presigned_url_contains_expiry() -> None:
    store = MinioStorage(client=FakeMinio(), bucket="b")
    url = store.presigned_get_url("a", expires_seconds=600)
    assert "expires=600" in url


def test_get_storage_is_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    get_storage.cache_clear()
    monkeypatch.setattr(
        storage_module,
        "get_settings",
        lambda: SimpleNamespace(
            minio_endpoint="localhost:9000",
            minio_root_user="u",
            minio_root_password="p",
            minio_bucket="b",
            minio_secure=False,
        ),
    )
    assert get_storage() is get_storage()
    get_storage.cache_clear()


def test_client_uses_secure_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_minio(endpoint, access_key, secret_key, secure):  # noqa: ANN001
        captured.update(endpoint=endpoint, secure=secure)
        return FakeMinio()

    monkeypatch.setattr(
        storage_module,
        "get_settings",
        lambda: SimpleNamespace(
            minio_endpoint="example:9000",
            minio_root_user="u",
            minio_root_password="p",
            minio_bucket="b",
            minio_secure=True,
        ),
    )
    monkeypatch.setattr(storage_module, "Minio", fake_minio)
    storage_module.MinioStorage().exists("x")
    assert captured == {"endpoint": "example:9000", "secure": True}