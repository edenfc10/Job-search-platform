from aijaa.core import repo


async def test_get_task_status_returns_existing_task(client, session):
    task_id, created = await repo.enqueue_task(
        session,
        task_type="run_matching",
        idempotency_key="match:test-seeker",
        payload={"seeker_id": "test-seeker"},
        seeker_id="test-seeker",
    )

    assert created is True

    response = await client.get(f"/v1/tasks/{task_id}")

    assert response.status_code == 200
    body = response.json()

    assert body["task_id"] == task_id
    assert body["task_type"] == "run_matching"
    assert body["seeker_id"] == "test-seeker"
    assert body["application_id"] is None
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["locked_at"] is None
    assert body["completed_at"] is None
    assert body["error"] is None
    assert "payload" not in body


async def test_get_task_status_returns_404_for_unknown_task(client):
    response = await client.get("/v1/tasks/missing-task")

    assert response.status_code == 404
    assert response.json() == {"detail": "task not found"}
