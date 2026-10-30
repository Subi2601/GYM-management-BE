from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def build_async_engine(database_url: str, echo: bool = False):
    return create_async_engine(
        database_url,
        echo=echo,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def build_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Each service instantiates this with its own DB URL from config.
# Usage in service main.py:
#   engine = build_async_engine(settings.DATABASE_URL)
#   AsyncSessionLocal = build_session_factory(engine)
#
# Then register the FastAPI dependency:
#   async def get_db() -> AsyncGenerator[AsyncSession, None]:
#       async with AsyncSessionLocal() as session:
#           yield session

async def get_db_dependency(session_factory: async_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
