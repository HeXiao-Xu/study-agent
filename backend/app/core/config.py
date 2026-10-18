"""应用配置：全项目唯一读 .env / 环境变量的入口（AGENTS.md：敏感项只从这里进程序）。

为什么 env_file 用绝对路径：uvicorn 可能从 backend/ 或仓库根启动，
相对路径会随启动目录不同而失灵；锚定本文件位置后，任何启动方式读到的
都是仓库根下同一个 .env。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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

    # --- 解析（S1-1）---
    # True=跳过 Docling 走 PyMuPDF 快速路径（spec 设计决策 6：显式开关而非自动猜）
    parse_force_pymupdf: bool = False

    # --- LLM（S1 起使用；铁律：Key 只能出现在 .env 与本配置）---
    llm_api_key: str = Field(default="", repr=False)  # repr=False：防止 Key 意外打进日志
    llm_base_url: str = ""

    # --- Embedding（S1-3；厂商 API，禁止本地大模型依赖）---
    embedding_provider: Literal["dashscope", "openai_compat", "local"] = "dashscope"
    # 两个字段分开收，空值回退：用户常只填标准名 DASHSCOPE_API_KEY
    embedding_api_key: str = Field(default="", repr=False)
    dashscope_api_key: str = Field(default="", repr=False)
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embedding_batch_size: int = 10  # DashScope v4 单次最多 10 行
    embedding_timeout_seconds: float = 60.0
    embedding_max_retries: int = 4
    # 元/百万 token（0.0005 元/千 token）；只用于估算展示，不写死调用逻辑
    embedding_price_per_million: float = 0.5

    @model_validator(mode="after")
    def _fallback_dashscope_key(self) -> "Settings":
        """EMBEDDING_API_KEY 为空时回退 DASHSCOPE_API_KEY。

        为什么不用 AliasChoices：.env 里 EMBEDDING_API_KEY= 是空字符串也算「已设置」，
        会导致用户只填标准名时反而取到空 Key。
        """
        if not self.embedding_api_key:
            self.embedding_api_key = self.dashscope_api_key
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """逗号分隔字符串 → 列表（CORS 中间件需要列表）。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """进程内单例：配置只解析一次，避免每个请求重复读 .env。"""
    return Settings()
