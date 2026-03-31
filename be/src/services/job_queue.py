from __future__ import annotations

from typing import Any

from arq import create_pool

from src.database.keydb.arq_config import get_arq_redis_settings
from src.settings import settings
from src.worker import tasks as worker_tasks


async def enqueue_task(function_name: str, *args, **kwargs) -> str:
    if settings.tasks_eager:
        function = getattr(worker_tasks, function_name)
        await function(None, *args, **kwargs)
        return f"eager-{function_name}"

    redis = await create_pool(get_arq_redis_settings())
    try:
        job = await redis.enqueue_job(function_name, *args, **kwargs)
        if job is None:
            raise RuntimeError(f"Failed to enqueue job {function_name}")
        return job.job_id
    finally:
        await redis.close()
