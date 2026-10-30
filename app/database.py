# async engine + session factory (built on shared package helpers)
from shared.database.session import build_async_engine, build_session_factory

from app.config import settings

engine = build_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = build_session_factory(engine)
