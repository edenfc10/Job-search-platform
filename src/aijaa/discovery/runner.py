"""Discovery runner: fetch from all configured sources, normalize, dedupe
(canonical_url unique constraint + fuzzy same-company/title), upsert."""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.discovery.base import JobSource, SearchCriteria


def _fuzzy_key(company: str, title: str, location: str | None) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "").lower())  # noqa: E731
    return f"{norm(company)}|{norm(title)}|{norm(location or '')}"


async def run_discovery(
    s: AsyncSession, sources: list[JobSource], criteria: SearchCriteria | None = None
) -> dict:
    from aijaa.discovery.normalize import normalize

    criteria = criteria or SearchCriteria(
        posted_within_days=get_settings().posted_within_days
    )
    stats = {"fetched": 0, "stale_dropped": 0, "created": 0, "updated": 0, "fuzzy_duped": 0}
    existing = await repo.list_postings(s)
    seen_fuzzy = {_fuzzy_key(p.company, p.title, p.location) for p in existing}

    for source in sources:
        raws = await source.fetch(criteria)
        stats["fetched"] += len(raws)
        for raw in raws:
            posting = normalize(raw, criteria.posted_within_days)
            if posting is None:
                stats["stale_dropped"] += 1
                continue
            key = _fuzzy_key(posting.company, posting.title, posting.location)
            _, created = await repo.upsert_posting(s, posting)
            if created:
                if key in seen_fuzzy:
                    stats["fuzzy_duped"] += 1
                seen_fuzzy.add(key)
                stats["created"] += 1
            else:
                stats["updated"] += 1
    return stats
