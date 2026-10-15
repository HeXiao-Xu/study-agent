"""应用配置：全项目唯一读 .env / 环境变量的入口（AGENTS.md：敏感项只从这里进程序）。

为什么 env_file 用绝对路径：uvicorn 可能从 backend/ 或仓库根启动，
相对路径会随启动目录不同而失灵；锚定本文件位置后，任何启动方式读到的
都是仓库根下同一个 .env。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py 向上 3 级 = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置；变量名与根目录 .env.example 一一对应。"""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # .env 里可能已有其他模块的变量：未声明的忽略而不报错
        extra="ignore",
    )

    # --- 应用 ---
    app_name: str = "study-agent"
    env: Literal["dev", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # 多个来源用逗号分隔（.env 里写纯字符串比写 JSON 对人友好）
    cors_origins: str = "http://localhost:5173"

    # --- 数据三件套（S0-4；database/redis 自 S1-3、minio 自 S2-6 起实际连接）---
    database_url: str = "postgresql+psycopg://study:study123@localhost:5432/study_agent"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "study"
    minio_root_password: str = "study123456"
    minio_bucket: str = "study-agent"

    # --- LLM（S1 起使用；铁律：Key 只能出现在 .env 与本配置）---
    llm_api_key: str = Field(default="", repr=False)  # repr=False：防止 Key 意外打进日志
    llm_base_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """逗号分隔字符串 → 列表（CORS 中间件需要列表）。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """进程内单例：配置只解析一次，避免每个请求重复读 .env。"""
    return Settings()
