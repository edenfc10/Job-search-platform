from aijaa.orchestration.redis_queue import get_redis_settings
from aijaa.orchestration.runner import run_task


async def execute_task(ctx: dict[str, object], task_id: str) -> bool:
    del ctx
    return await run_task(task_id)


class WorkerSettings:
    functions = [execute_task]
    redis_settings = get_redis_settings()
    max_jobs = 10
    job_timeout = 600
