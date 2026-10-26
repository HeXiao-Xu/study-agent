"""对象存储适配器（S2-6）：协议 + MinIO 实现 + 进程内单例。

路由只依赖 put/exists/delete 这些语义方法，测试注入假实现即可，套件不连 MinIO。
对外错误固定「文件存储不可用」，不把 endpoint/凭据带进响应。
"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import BinaryIO, Protocol

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings
from app.core.exceptions import StorageUnavailableError

_CHUNK = 64 * 1024
_MISSING_CODES = {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}


class ObjectStorage(Protocol):
    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def download_to(self, key: str, target: BinaryIO) -> None: ...

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str: ...


class MinioStorage:
    """懒连接、懒建桶：桶由 compose 的 minio-init 建，这里只做自愈。"""

    def __init__(self, client: Minio | None = None, *, bucket: str | None = None) -> None:
        self._bucket = bucket or get_settings().minio_bucket
        self._client = client
        self._bucket_ready = False

    def _client_obj(self) -> Minio:
        if self._client is None:
            settings = get_settings()
            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_root_user,
                secret_key=settings.minio_root_password,
                secure=settings.minio_secure,
            )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        client = self._client_obj()
        try:
            if not client.bucket_exists(self._bucket):
                client.make_bucket(self._bucket)
        except Exception as exc:  # SDK 异常类型多，统一收敛
            raise StorageUnavailableError() from exc
        self._bucket_ready = True

    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        self._ensure_bucket()
        client = self._client_obj()
        try:
            client.put_object(
                self._bucket, key, data, length=size, content_type=content_type
            )
            stat = client.stat_object(self._bucket, key)
        except Exception as exc:
            raise StorageUnavailableError() from exc
        if getattr(stat, "size", size) != size:
            # 落盘字节数与声明不一致：宁可报错，也不留半截对象
            self.delete(key)
            raise StorageUnavailableError()

    def exists(self, key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client_obj().stat_object(self._bucket, key)
            return True
        except S3Error as exc:
            if exc.code in _MISSING_CODES:
                return False
            raise StorageUnavailableError() from exc
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def delete(self, key: str) -> None:
        self._ensure_bucket()
        try:
            self._client_obj().remove_object(self._bucket, key)
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def download_to(self, key: str, target: BinaryIO) -> None:
        self._ensure_bucket()
        client = self._client_obj()
        try:
            response = client.get_object(self._bucket, key)
            try:
                for chunk in response.stream(_CHUNK):
                    target.write(chunk)
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            raise StorageUnavailableError() from exc

    def presigned_get_url(self, key: str, *, expires_seconds: int = 3600) -> str:
        self._ensure_bucket()
        try:
            return self._client_obj().presigned_get_object(
                self._bucket, key, expires=timedelta(seconds=expires_seconds)
            )
        except Exception as exc:
            raise StorageUnavailableError() from exc


@lru_cache
def get_storage() -> ObjectStorage:
    """进程内单例；FastAPI 依赖与测试覆盖共用同一入口。"""
    return MinioStorage()