import asyncpg
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator

from jobdbmcp.config import Settings


@dataclass
class AppContext:
    pool: asyncpg.Pool


@asynccontextmanager
async def pool_lifespan(settings: Settings) -> AsyncIterator[AppContext]:
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
    )
    try:
        yield AppContext(pool=pool)
    finally:
        await pool.close()
