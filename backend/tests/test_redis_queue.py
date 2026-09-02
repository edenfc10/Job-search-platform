from aijaa.orchestration import worker
from aijaa.orchestration.redis_queue import TASK_JOB_NAME, enqueue_task_delivery


class FakeRedis:
    def __init__(self, result):
        self.result = result
        self.call = None

    async def enqueue_job(self, function_name, task_id, **kwargs):
        self.call = (function_name, task_id, kwargs)
        return self.result


async def test_enqueue_task_delivery_uses_task_id_as_job_id():
    redis = FakeRedis(result=object())

    created = await enqueue_task_delivery(redis, "task-123")

    assert created is True
    assert redis.call == (TASK_JOB_NAME, "task-123", {"_job_id": "task-123"})


async def test_enqueue_task_delivery_reports_existing_job():
    redis = FakeRedis(result=None)

    created = await enqueue_task_delivery(redis, "task-123")

    assert created is False


async def test_worker_dispatches_exact_task_id(monkeypatch):
    received = []

    async def fake_run_task(task_id):
        received.append(task_id)
        return True

    monkeypatch.setattr(worker, "run_task", fake_run_task)

    assert await worker.execute_task({}, "task-123") is True
    assert received == ["task-123"]
