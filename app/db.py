from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_config
from app.models import Base


config = get_config()
engine_kwargs = {"future": True, "echo": False}
if config.database.url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"timeout": 30}
engine = create_async_engine(config.database.url, **engine_kwargs)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if config.database.url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


@asynccontextmanager
async def get_session() -> AsyncSession:
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
