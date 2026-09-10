import json
import asyncpg
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator

from jobdbmcp.config import Settings


@dataclass
class AppContext:
    pool: asyncpg.Pool


async def init_connection(connection: asyncpg.Connection) -> None:
    # asyncpg exchanges jsonb as text by default; decode it to Python values instead.
    await connection.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


@asynccontextmanager
async def pool_lifespan(settings: Settings) -> AsyncIterator[AppContext]:
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        init=init_connection,
    )
    try:
        yield AppContext(pool=pool)
    finally:
        await pool.close()
