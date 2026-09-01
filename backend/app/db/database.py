"""SQLAlchemy 数据库连接管理。

默认 SQLite(零配置),通过 DB_URL 可无缝切换 MySQL,
业务代码全部基于 SQLAlchemy,不感知具体数据库方言差异。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..config import get_settings


def _create_engine():
    settings = get_settings()
    url = settings.db_url
    # 相对路径的 SQLite 锚定到 backend 目录(MCP stdio 子进程的 CWD 不可控)
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        path = url[len("sqlite:///"):]
        if path and not Path(path).is_absolute():
            url = f"sqlite:///{(settings.base_dir / path).as_posix()}"
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif url.startswith("mysql"):
        kwargs["pool_size"] = 5
        kwargs["pool_recycle"] = 3600
    return create_engine(url, **kwargs)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def health_check() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
