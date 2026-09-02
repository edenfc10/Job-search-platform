from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.db import get_session

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])


class TaskStatusResponse(BaseModel):
    task_id: str
    task_type: str
    seeker_id: str | None
    application_id: str | None
    status: str
    attempts: int
    run_after: datetime
    locked_at: datetime | None
    completed_at: datetime | None
    error: str | None


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    s: AsyncSession = Depends(get_session),
) -> TaskStatusResponse:
    task = await repo.get_task(s, task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    return TaskStatusResponse(
        task_id=task.id,
        task_type=task.task_type,
        seeker_id=task.seeker_id or None,
        application_id=task.application_id or None,
        status=task.status,
        attempts=task.attempts,
        run_after=task.run_after,
        locked_at=task.locked_at,
        completed_at=task.completed_at,
        error=task.error or None,
    )
