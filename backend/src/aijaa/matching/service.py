"""Matching pipeline: hard filters -> vector retrieval -> Claude re-rank ->
match floor (PRD: scores below settings.match_floor are WITHHELD, never
surfaced) -> persisted MatchResults + ApplicationRecords."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord, MatchResult
from aijaa.core.profile_quality import candidate_profile_issues
from aijaa.core.status import ApplicationStatus
from aijaa.llm.factory import get_llms
from aijaa.matching.embedder import cosine, get_embedder
from aijaa.matching.filters import passes_hard_filters

log = structlog.get_logger()


def seeker_query_text(profile, prefs) -> str:
    return " ".join(
        [e.title for e in profile.work_history]
        + [f.text for f in profile.skills]
        + [f.text for e in profile.work_history for f in e.achievements[:2]]
        + prefs.target_titles
        + prefs.industries
    )


async def run_matching(s: AsyncSession, seeker_id: str) -> dict:
    settings = get_settings()
    profile = await repo.latest_profile(s, seeker_id)
    prefs = await repo.get_preferences(s, seeker_id)
    if profile is None or prefs is None:
        raise ValueError("seeker has no profile/preferences — run intake first")
    quality_issues = candidate_profile_issues(profile, prefs)
    if quality_issues:
        raise ValueError(
            "profile is not ready for job matching: " + "; ".join(quality_issues)
        )

    warnings = []
    if repo.profile_is_stale(profile, settings.profile_stale_days):
        warnings.append(f"profile is older than {settings.profile_stale_days} days — re-validate before applying")

    postings = await repo.list_postings(s)
    already_matched = {m.posting_id for m in await repo.list_matches(s, seeker_id)}
    unmatched = [p for p in postings if p.id not in already_matched]
    candidates = [p for p in unmatched if passes_hard_filters(p, prefs)]

    embedder = get_embedder()
    query_vec = await embedder.embed(seeker_query_text(profile, prefs))
    scored = []
    for p in candidates:
        vec = await repo.get_posting_embedding(s, p.id)
        if vec is None:
            vec = await embedder.embed(p.title + " " + p.description_text[:4000])
            await repo.set_posting_embedding(s, p.id, vec)
        scored.append((cosine(query_vec, vec), p))
    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[: settings.rerank_top_k]

    items = await get_llms().rerank.rerank(profile, prefs, [p for _, p in top])
    vec_by_id = {p.id: v for v, p in top}

    created = 0
    withheld = 0
    for item in sorted(items, key=lambda i: i.score, reverse=True):
        if item.score < settings.match_floor:
            withheld += 1
            continue  # PRD invariant: below the floor we withhold, not display
        if created >= settings.match_top_n:
            break
        match = MatchResult(
            seeker_id=seeker_id,
            posting_id=item.posting_id,
            vector_score=round(vec_by_id.get(item.posting_id, 0.0), 4),
            rerank_score=item.score,
            rationale=item.rationale,
            risks=item.risks,
        )
        match_id = await repo.create_match(s, match)
        if match_id is None:
            continue  # idempotent: match already exists for this pair
        app = ApplicationRecord(
            seeker_id=seeker_id,
            posting_id=item.posting_id,
            match_id=match_id,
            status=ApplicationStatus.discovered.value,
        )
        app_id = await repo.create_application(s, app)
        if app_id:
            await repo.transition_application(s, app, ApplicationStatus.matched.value, "system",
                                              f"rerank={item.score}")
        created += 1

    stats = {
        "jobs_considered": len(postings),
        "already_matched": len(postings) - len(unmatched),
        "hard_filtered": len(unmatched) - len(candidates),
        "candidates_after_filters": len(candidates),
        "reranked": len(items),
        "matches_created": created,
        "withheld_below_floor": withheld,
        "match_floor": settings.match_floor,
        "warnings": warnings,
    }
    log.info("matching_run", seeker_id=seeker_id, **stats)
    return stats
