"""S1-3 配置测试：Embedding 默认值与 Key 别名（spec §9.1）。"""
from __future__ import annotations

from app.core.config import Settings


def test_embedding_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_provider == "dashscope"
    assert s.embedding_model == "text-embedding-v4"
    assert s.embedding_dim == 1024
    assert s.embedding_batch_size == 10  # 厂商硬上限，不是任务卡的 32
    assert s.embedding_price_per_million == 0.5


def test_embedding_key_accepts_dashscope_alias(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-dashscope"
    assert "sk-test-dashscope" not in repr(s)


def test_embedding_key_empty_embedding_falls_back_to_dashscope(monkeypatch) -> None:
    """真实 .env 常同时有空的 EMBEDDING_API_KEY= 与 DASHSCOPE_API_KEY=。"""
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-fallback")
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-fallback"


def test_embedding_key_accepts_embedding_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test-embedding")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-embedding"


def test_embedding_key_embedding_env_wins_when_both_set(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test-explicit")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-dashscope")
    s = Settings(_env_file=None)
    assert s.embedding_api_key == "sk-test-explicit"
