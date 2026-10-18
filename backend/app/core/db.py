"""SQLAlchemy 基座：Engine/Session/Base 的唯一入口（S1-3 首次接入数据库）。"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """所有 ORM 模型的基类；Alembic 的 target_metadata 指向它的 metadata。"""


def get_engine() -> Engine:
    """惰性建引擎：import 模型/跑纯单测时不触发任何数据库连接。"""
    global _engine
    if _engine is None:
        # hide_parameters=True：异常信息里不出现连接参数（含密码）
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


def new_session() -> Session:
    """CLI/Worker 用；调用方负责 `with new_session() as session:` 关闭。"""
    return get_session_factory()()
