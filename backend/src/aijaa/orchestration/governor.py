"""Local governance for the in-process task runner."""

from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord, utcnow


def domain_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.split(":")[0]


async def can_start_browser_task(
    s: AsyncSession, seeker_id: str, exclude_task_id: str | None = None
) -> tuple[bool, str]:
    """`exclude_task_id` is the id of the task making this check — it is
    already marked 'running' by the time this runs, so it must be excluded
    from its own active-count check or every task blocks on itself."""
    settings = get_settings()
    if await repo.active_browser_tasks(s, exclude_task_id=exclude_task_id) >= settings.browser_pool_max:
        return False, "browser_pool_full"
    if await repo.active_browser_tasks(s, seeker_id, exclude_task_id=exclude_task_id) >= 1:
        return False, "seeker_browser_busy"
    return True, ""


async def can_start_application(
    s: AsyncSession, app: ApplicationRecord, apply_url: str
) -> tuple[bool, str, int]:
    settings = get_settings()
    started = await repo.applications_started_since(
        s, app.seeker_id, utcnow() - timedelta(days=1)
    )
    if started >= settings.applications_per_day:
        return False, "daily_application_cap", 3600

    domain = domain_for_url(apply_url)
    if domain:
        next_allowed = await repo.domain_next_allowed(s, domain)
        now = utcnow()
        if next_allowed and next_allowed.tzinfo is None:
            next_allowed = next_allowed.replace(tzinfo=now.tzinfo)
        if next_allowed and next_allowed > now:
            return False, "domain_rate_limited", max(1, int((next_allowed - now).total_seconds()))
        await repo.reserve_domain(s, domain, settings.domain_application_interval_seconds)
    return True, "", 0
