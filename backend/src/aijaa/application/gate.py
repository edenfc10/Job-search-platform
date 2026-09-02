"""The approval gate. Nothing downstream of matching may act without an
explicit, attributed, per-job human approval. There is no auto-approve flag
and none may be added."""

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.models import ApplicationRecord


class ApprovalMissing(Exception):
    pass


async def require_approval(s: AsyncSession, app: ApplicationRecord) -> None:
    match = await repo.get_match(s, app.match_id)
    if match is None or match.status != "approved" or not match.decided_by:
        raise ApprovalMissing(
            f"application {app.id} has no approved decision (match={app.match_id})"
        )
