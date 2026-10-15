"""FastAPI 应用装配：本文件只做组装，不写业务（分层见 AGENTS.md §4）。

启动（在 backend/ 目录下）：
    uvicorn app.main:app --reload
验收（任务卡）：
    curl http://127.0.0.1:8000/health              → 200 统一成功壳
    curl http://127.0.0.1:8000/not-exist-route     → 404 统一错误壳 + X-Trace-Id
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.context import get_trace_id
from app.core.exceptions import install_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import TraceIdMiddleware
from app.schemas.common import Envelope, HealthData


def create_app() -> FastAPI:
    """应用工厂：uvicorn 入口与测试共用同一条装配路径，保证测的就是跑的。"""
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version=__version__)

    # add_middleware 后添加的在最外层：把 TraceId 放最外，让 trace_id 包住 CORS 等所有环节
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceIdMiddleware)

    install_exception_handlers(app)

    @app.get("/health", response_model=Envelope[HealthData], tags=["meta"], summary="健康检查")
    async def health() -> Envelope[HealthData]:
        # 纯心跳不连库：三件套健康归 scripts/check_services.py，端到端冒烟归 S0-7
        return Envelope[HealthData](
            trace_id=get_trace_id(),
            data=HealthData(status="ok", app=settings.app_name, version=__version__, env=settings.env),
        )

    return app


app = create_app()
