"""
Redis connection management for the FastAPI process.

  - arq_pool  : used to enqueue jobs (write to ARQ queue)
  - relay_pool: used to read events from Redis Streams (XREAD)

Call init_redis() on startup and close_redis() on shutdown.
"""

import os

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_arq_pool = None
_relay_pool: aioredis.ConnectionPool | None = None


async def init_redis() -> None:
    global _arq_pool, _relay_pool
    settings = RedisSettings.from_dsn(REDIS_URL)
    _arq_pool = await create_pool(settings)
    _relay_pool = aioredis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    global _arq_pool, _relay_pool
    if _arq_pool:
        await _arq_pool.close()
        _arq_pool = None
    if _relay_pool:
        await _relay_pool.disconnect()
        _relay_pool = None


def get_arq_pool():
    """Return the ARQ pool for enqueuing jobs."""
    if _arq_pool is None:
        raise RuntimeError("Redis not initialised — call init_redis() on startup")
    return _arq_pool


def get_relay_redis() -> aioredis.Redis:
    """Return a Redis client for stream relay (one connection per call, from pool)."""
    if _relay_pool is None:
        raise RuntimeError("Redis not initialised — call init_redis() on startup")
    return aioredis.Redis(connection_pool=_relay_pool)
