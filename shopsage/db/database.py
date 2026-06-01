"""
Asynchronous SQLAlchemy database setup.
Handles connection pooling and session management.
"""

import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from shopsage.config import settings

logger = logging.getLogger("shopsage.db")

# SQLAlchemy base model class
Base = declarative_base()

# Async Engine setup
# For SQLite, we don't need pool_size or max_overflow. 
# For PostgreSQL, we will use connection pooling.
is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine_kwargs = {}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_recycle": 1800, # Recycle connections every 30 minutes
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    **engine_kwargs
)

# Async session maker
async_session = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

async def init_db():
    """Initialize the database schema (useful for dev/testing before Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("[Database] Initialised SQLAlchemy schema")

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency provider for FastAPI endpoints."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
