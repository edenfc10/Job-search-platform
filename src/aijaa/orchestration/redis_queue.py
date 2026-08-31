from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from aijaa.core.config import get_settings

TASK_JOB_NAME = "execute_task"


def get_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def create_queue_pool() -> ArqRedis:
    return await create_pool(get_redis_settings())


async def enqueue_task_delivery(redis: ArqRedis, task_id: str) -> bool:
    job = await redis.enqueue_job(
        TASK_JOB_NAME,
        task_id,
        _job_id=task_id,
    )
    return job is not None
