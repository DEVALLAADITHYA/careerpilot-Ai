from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.models import Base

_engine = None
_Session: sessionmaker | None = None


def configure(url: str | None = None) -> None:
    """(Re)create the engine and tables. API keys are never stored in the DB."""
    global _engine, _Session
    url = url or get_settings().database_url
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    _engine = create_engine(url, **kw)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope():
    if _Session is None:
        configure()
    s: Session = _Session()  # type: ignore[misc]
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
