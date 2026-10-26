"""ARQ 队列适配器（S2-7）。

提交是低频动作（每次上传一次），所以每次 asyncio.run 建短连接；
比维护后台事件循环线程简单，测试也能直接注入 TaskQueue 假实现。

注意：ARQ 0.28 的 enqueue_job 没有 _max_tries/_job_timeout 参数，
超时与重试次数只能配在 WorkerSettings（worker.py）。
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Protocol

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.exceptions import TaskQueueUnavailableError


class TaskQueue(Protocol):
    def enqueue(self, name: str, task_id: int) -> None: ...


class ArqTaskQueue:
    def enqueue(self, name: str, task_id: int) -> None:
        asyncio.run(self._enqueue(name, task_id))

    async def _enqueue(self, name: str, task_id: int) -> None:
        settings = get_settings()
        pool = None
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            job = await pool.enqueue_job("run_task", task_id, _job_id=f"task:{task_id}")
            if job is None:
                raise TaskQueueUnavailableError()
        except TaskQueueUnavailableError:
            raise
        except Exception as exc:  # Redis/连接/序列化异常统一收敛，不泄露地址
            raise TaskQueueUnavailableError() from exc
        finally:
            if pool is not None:
                try:
                    await pool.aclose()
                except Exception:  # 关闭失败不影响已入队结果
                    pass


@lru_cache
def get_task_queue() -> TaskQueue:
    return ArqTaskQueue()