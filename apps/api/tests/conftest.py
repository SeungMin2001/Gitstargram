import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings


@pytest_asyncio.fixture
async def isolated_db():
    """Rollback all fixture data, even when a service commits internally."""
    engine = create_async_engine(settings().database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    await engine.dispose()
