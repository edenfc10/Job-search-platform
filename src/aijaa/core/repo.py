"""Repository layer. Tenancy rule: every seeker-scoped read/write REQUIRES
seeker_id. Domain code never queries tables directly."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import tables as t
from aijaa.core.models import (
    ApplicationRecord,
    CareerPreferences,
    JobPosting,
    MatchResult,
    ProfessionalProfile,
    ResumeDocument,
    new_id,
    utcnow,
)
from aijaa.core.status import transition_entry

# -------------------------------------------------------------------------- seekers


async def create_seeker(s: AsyncSession, external_ref: str, consent_at: datetime) -> str:
    seeker_id = new_id()
    s.add(
        t.SeekerRow(
            id=seeker_id,
            external_ref=external_ref,
            consent_recorded_at=consent_at,
            created_at=utcnow(),
        )
    )
    await s.commit()
    return seeker_id


async def get_seeker(s: AsyncSession, seeker_id: str) -> t.SeekerRow | None:
    return await s.get(t.SeekerRow, seeker_id)


# ------------------------------------------------------------------------- profiles


async def latest_profile(s: AsyncSession, seeker_id: str) -> ProfessionalProfile | None:
    row = (
        await s.execute(
            select(t.ProfileRow)
            .where(t.ProfileRow.seeker_id == seeker_id)
            .order_by(t.ProfileRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ProfessionalProfile.model_validate(row.data) if row else None


async def save_profile(s: AsyncSession, seeker_id: str, profile: ProfessionalProfile) -> int:
    prev = await latest_profile(s, seeker_id)
    profile.seeker_id = seeker_id
    profile.version = (prev.version + 1) if prev else 1
    profile.updated_at = utcnow()
    s.add(
        t.ProfileRow(
            seeker_id=seeker_id, version=profile.version, data=profile.model_dump(mode="json")
        )
    )
    await s.commit()
    return profile.version


def profile_is_stale(profile: ProfessionalProfile, stale_days: int) -> bool:
    updated = profile.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return (utcnow() - updated).days >= stale_days


async def get_preferences(s: AsyncSession, seeker_id: str) -> CareerPreferences | None:
    row = await s.get(t.PreferencesRow, seeker_id)
    return CareerPreferences.model_validate(row.data) if row else None


async def save_preferences(s: AsyncSession, seeker_id: str, prefs: CareerPreferences) -> None:
    prefs.seeker_id = seeker_id
    row = await s.get(t.PreferencesRow, seeker_id)
    if row:
        row.data = prefs.model_dump(mode="json")
    else:
        s.add(t.PreferencesRow(seeker_id=seeker_id, data=prefs.model_dump(mode="json")))
    await s.commit()


# ------------------------------------------------------------------------- postings


async def upsert_posting(s: AsyncSession, posting: JobPosting) -> tuple[str, bool]:
    """Returns (posting_id, created)."""
    existing = (
        await s.execute(
            select(t.PostingRow).where(t.PostingRow.canonical_url == posting.canonical_url)
        )
    ).scalar_one_or_none()
    if existing:
        posting.id = existing.id
        posting.first_seen_at = existing.first_seen_at
        posting.last_seen_at = utcnow()
        existing.data = posting.model_dump(mode="json")
        existing.source = posting.source
        existing.company = posting.company
        existing.title = posting.title
        existing.content_hash = posting.content_hash
        existing.posted_at = posting.posted_at
        await s.commit()
        return existing.id, False
    s.add(
        t.PostingRow(
            id=posting.id,
            canonical_url=posting.canonical_url,
            source=posting.source,
            company=posting.company,
            title=posting.title,
            content_hash=posting.content_hash,
            posted_at=posting.posted_at,
            first_seen_at=posting.first_seen_at,
            data=posting.model_dump(mode="json"),
        )
    )
    await s.commit()
    return posting.id, True


async def list_postings(s: AsyncSession) -> list[JobPosting]:
    rows = (await s.execute(select(t.PostingRow))).scalars().all()
    return [JobPosting.model_validate(r.data) for r in rows]


async def get_posting(s: AsyncSession, posting_id: str) -> JobPosting | None:
    row = await s.get(t.PostingRow, posting_id)
    return JobPosting.model_validate(row.data) if row else None


async def set_posting_embedding(s: AsyncSession, posting_id: str, vec: list[float]) -> None:
    await s.execute(
        update(t.PostingRow).where(t.PostingRow.id == posting_id).values(embedding=vec)
    )
    await s.commit()


async def get_posting_embedding(s: AsyncSession, posting_id: str) -> list[float] | None:
    row = await s.get(t.PostingRow, posting_id)
    return row.embedding if row else None


async def update_posting(s: AsyncSession, posting: JobPosting) -> None:
    row = await s.get(t.PostingRow, posting.id)
    if row:
        row.data = posting.model_dump(mode="json")
        await s.commit()


# -------------------------------------------------------------------------- matches


async def create_match(s: AsyncSession, match: MatchResult) -> str | None:
    """Idempotent on (seeker_id, posting_id): returns None if one already exists."""
    dupe = (
        await s.execute(
            select(t.MatchRow).where(
                t.MatchRow.seeker_id == match.seeker_id,
                t.MatchRow.posting_id == match.posting_id,
            )
        )
    ).scalar_one_or_none()
    if dupe:
        return None
    s.add(
        t.MatchRow(
            id=match.id,
            seeker_id=match.seeker_id,
            posting_id=match.posting_id,
            status=match.status,
            rerank_score=match.rerank_score,
            data=match.model_dump(mode="json"),
        )
    )
    await s.commit()
    return match.id


async def list_matches(s: AsyncSession, seeker_id: str, status: str | None = None) -> list[MatchResult]:
    q = select(t.MatchRow).where(t.MatchRow.seeker_id == seeker_id)
    if status:
        q = q.where(t.MatchRow.status == status)
    rows = (await s.execute(q.order_by(t.MatchRow.rerank_score.desc()))).scalars().all()
    return [MatchResult.model_validate(r.data) for r in rows]


async def get_match(s: AsyncSession, match_id: str) -> MatchResult | None:
    row = await s.get(t.MatchRow, match_id)
    return MatchResult.model_validate(row.data) if row else None


async def save_match(s: AsyncSession, match: MatchResult) -> None:
    row = await s.get(t.MatchRow, match.id)
    if row:
        row.status = match.status
        row.rerank_score = match.rerank_score
        row.data = match.model_dump(mode="json")
        await s.commit()


# --------------------------------------------------------------------------- resumes


async def save_resume(s: AsyncSession, resume: ResumeDocument) -> str:
    s.add(
        t.ResumeRow(
            id=resume.id,
            seeker_id=resume.seeker_id,
            kind=resume.kind,
            language=resume.language,
            posting_id=resume.posting_id,
            created_at=resume.created_at,
            data=resume.model_dump(mode="json"),
        )
    )
    await s.commit()
    return resume.id


async def latest_master_resume(
    s: AsyncSession, seeker_id: str, language: str
) -> ResumeDocument | None:
    row = (
        await s.execute(
            select(t.ResumeRow)
            .where(
                t.ResumeRow.seeker_id == seeker_id,
                t.ResumeRow.kind == "master",
                t.ResumeRow.language == language,
            )
            .order_by(t.ResumeRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ResumeDocument.model_validate(row.data) if row else None


async def get_resume(s: AsyncSession, seeker_id: str, resume_id: str) -> ResumeDocument | None:
    row = await s.get(t.ResumeRow, resume_id)
    if row is None or row.seeker_id != seeker_id:
        return None
    return ResumeDocument.model_validate(row.data)


# ---------------------------------------------------------------------- applications


async def create_application(s: AsyncSession, app: ApplicationRecord) -> str | None:
    """Idempotent on (seeker_id, posting_id)."""
    dupe = (
        await s.execute(
            select(t.ApplicationRow).where(
                t.ApplicationRow.seeker_id == app.seeker_id,
                t.ApplicationRow.posting_id == app.posting_id,
            )
        )
    ).scalar_one_or_none()
    if dupe:
        return None
    s.add(
        t.ApplicationRow(
            id=app.id,
            seeker_id=app.seeker_id,
            posting_id=app.posting_id,
            status=app.status,
            submitted_at=app.submitted_at,
            data=app.model_dump(mode="json"),
        )
    )
    await s.commit()
    return app.id


async def get_application(s: AsyncSession, application_id: str) -> ApplicationRecord | None:
    row = await s.get(t.ApplicationRow, application_id)
    return ApplicationRecord.model_validate(row.data) if row else None


async def get_application_for_match(s: AsyncSession, match_id: str) -> ApplicationRecord | None:
    rows = (await s.execute(select(t.ApplicationRow))).scalars().all()
    for r in rows:
        if r.data.get("match_id") == match_id:
            return ApplicationRecord.model_validate(r.data)
    return None


async def list_applications(
    s: AsyncSession, seeker_id: str, status: str | None = None
) -> list[ApplicationRecord]:
    q = select(t.ApplicationRow).where(t.ApplicationRow.seeker_id == seeker_id)
    if status:
        q = q.where(t.ApplicationRow.status == status)
    rows = (await s.execute(q)).scalars().all()
    return [ApplicationRecord.model_validate(r.data) for r in rows]


async def save_application(s: AsyncSession, app: ApplicationRecord) -> None:
    row = await s.get(t.ApplicationRow, app.id)
    if row:
        row.status = app.status
        row.submitted_at = app.submitted_at
        row.data = app.model_dump(mode="json")
        await s.commit()


async def transition_application(
    s: AsyncSession,
    app: ApplicationRecord,
    new_status: str,
    actor: str,
    reason: str | None = None,
) -> ApplicationRecord:
    """The ONLY way application status changes. Validates the state machine,
    appends the timeline entry, persists, and writes an audit event."""
    entry = transition_entry(app.status, new_status, actor, reason)
    app.status = new_status
    app.timeline.append(entry)
    await save_application(s, app)
    await audit(
        s,
        seeker_id=app.seeker_id,
        entity_type="application",
        entity_id=app.id,
        event=f"status:{entry['from']}->{entry['to']}",
        actor=actor,
        detail={"reason": reason},
    )
    return app


# ----------------------------------------------------------------------------- audit


async def audit(
    s: AsyncSession,
    seeker_id: str,
    entity_type: str,
    entity_id: str,
    event: str,
    actor: str,
    detail: dict | None = None,
) -> None:
    s.add(
        t.AuditRow(
            ts=utcnow(),
            seeker_id=seeker_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event=event,
            actor=actor,
            detail=detail or {},
        )
    )
    await s.commit()


async def audit_for_entity(s: AsyncSession, seeker_id: str, entity_id: str) -> list[dict]:
    rows = (
        await s.execute(
            select(t.AuditRow)
            .where(t.AuditRow.seeker_id == seeker_id, t.AuditRow.entity_id == entity_id)
            .order_by(t.AuditRow.ts)
        )
    ).scalars().all()
    return [
        {
            "ts": r.ts.isoformat(),
            "event": r.event,
            "actor": r.actor,
            "detail": r.detail,
        }
        for r in rows
    ]


async def add_llm_usage(
    s: AsyncSession, seeker_id: str, component: str, model: str, input_tokens: int, output_tokens: int
) -> None:
    s.add(
        t.LLMUsageRow(
            ts=utcnow(),
            seeker_id=seeker_id,
            component=component,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    )
    await s.commit()


# --------------------------------------------------------------------------- tasks


async def enqueue_task(
    s: AsyncSession,
    task_type: str,
    idempotency_key: str,
    payload: dict | None = None,
    seeker_id: str = "",
    application_id: str = "",
    run_after: datetime | None = None,
) -> tuple[str, bool]:
    """Create a queued task unless an equivalent unfinished/done task exists."""
    existing = (
        await s.execute(
            select(t.TaskRow).where(t.TaskRow.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing:
        return existing.id, False
    task_id = new_id()
    s.add(
        t.TaskRow(
            id=task_id,
            task_type=task_type,
            idempotency_key=idempotency_key,
            seeker_id=seeker_id,
            application_id=application_id,
            status="queued",
            run_after=run_after or utcnow(),
            payload=payload or {},
        )
    )
    await s.commit()
    return task_id, True


async def list_tasks(
    s: AsyncSession, status: str | None = None, seeker_id: str | None = None
) -> list[t.TaskRow]:
    q = select(t.TaskRow)
    if status:
        q = q.where(t.TaskRow.status == status)
    if seeker_id:
        q = q.where(t.TaskRow.seeker_id == seeker_id)
    return (await s.execute(q.order_by(t.TaskRow.run_after, t.TaskRow.id))).scalars().all()


async def claim_due_task(s: AsyncSession) -> t.TaskRow | None:
    row = (
        await s.execute(
            select(t.TaskRow)
            .where(t.TaskRow.status == "queued", t.TaskRow.run_after <= utcnow())
            .order_by(t.TaskRow.run_after, t.TaskRow.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.status = "running"
    row.locked_at = utcnow()
    row.attempts += 1
    await s.commit()
    return row


async def claim_task_by_id(s: AsyncSession, task_id: str) -> t.TaskRow | None:
    row = (
        await s.execute(
            select(t.TaskRow)
            .where(
                t.TaskRow.id == task_id,
                t.TaskRow.status == "queued",
                t.TaskRow.run_after <= utcnow(),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()

    if row is None:
        return None

    row.status = "running"
    row.locked_at = utcnow()
    row.attempts += 1
    await s.commit()
    return row


async def complete_task(s: AsyncSession, task_id: str) -> None:
    row = await s.get(t.TaskRow, task_id)
    if row:
        row.status = "succeeded"
        row.completed_at = utcnow()
        await s.commit()


async def complete_queued_tasks_for_application(
    s: AsyncSession, application_id: str, task_types: set[str]
) -> int:
    """Mark queued work as superseded when its stage already ran inline.

    The current console remains synchronous for compatibility. Without this,
    approval-created tasks stay queued forever when no separate local runner is
    active and make the operational data misleading.
    """
    rows = (
        await s.execute(
            select(t.TaskRow).where(
                t.TaskRow.application_id == application_id,
                t.TaskRow.status == "queued",
                t.TaskRow.task_type.in_(task_types),
            )
        )
    ).scalars().all()
    for row in rows:
        row.status = "succeeded"
        row.completed_at = utcnow()
        row.error = "superseded by synchronous API execution"
    if rows:
        await s.commit()
    return len(rows)


async def fail_task(
    s: AsyncSession, task_id: str, error: str, retry_after_seconds: int | None = None
) -> None:
    row = await s.get(t.TaskRow, task_id)
    if row is None:
        return
    row.error = error[:2048]
    if retry_after_seconds is not None and row.attempts < 3:
        row.status = "queued"
        row.run_after = utcnow() + timedelta(seconds=retry_after_seconds)
    else:
        row.status = "dead_letter"
        s.add(
            t.DeadLetterRow(
                task_id=row.id,
                task_type=row.task_type,
                seeker_id=row.seeker_id,
                application_id=row.application_id,
                failed_at=utcnow(),
                error=row.error,
                payload=row.payload,
            )
        )
    await s.commit()


async def task_counts(s: AsyncSession, seeker_id: str | None = None) -> dict[str, int]:
    q = select(t.TaskRow.status, func.count()).group_by(t.TaskRow.status)
    if seeker_id:
        q = q.where(t.TaskRow.seeker_id == seeker_id)
    rows = (await s.execute(q)).all()
    return {status: count for status, count in rows}


async def dead_letter_count(s: AsyncSession, seeker_id: str | None = None) -> int:
    q = select(func.count()).select_from(t.DeadLetterRow)
    if seeker_id:
        q = q.where(t.DeadLetterRow.seeker_id == seeker_id)
    return int((await s.execute(q)).scalar_one())


async def active_browser_tasks(
    s: AsyncSession, seeker_id: str | None = None, exclude_task_id: str | None = None
) -> int:
    """Count of currently-running browser-stage tasks. `exclude_task_id` must be
    passed by a task checking whether it itself may proceed — `claim_due_task`
    marks a task 'running' before it runs, so without excluding its own id, a
    task always counts itself as already active and can never start."""
    browser_types = {"run_analyze", "run_apply", "resume_after_human"}
    q = select(func.count()).select_from(t.TaskRow).where(
        t.TaskRow.status == "running", t.TaskRow.task_type.in_(browser_types)
    )
    if seeker_id:
        q = q.where(t.TaskRow.seeker_id == seeker_id)
    if exclude_task_id:
        q = q.where(t.TaskRow.id != exclude_task_id)
    return int((await s.execute(q)).scalar_one())


async def applications_started_since(s: AsyncSession, seeker_id: str, since: datetime) -> int:
    rows = (
        await s.execute(
            select(t.AuditRow).where(
                t.AuditRow.seeker_id == seeker_id,
                t.AuditRow.event == "application_start",
                t.AuditRow.ts >= since,
            )
        )
    ).scalars().all()
    return len(rows)


async def domain_next_allowed(s: AsyncSession, domain: str) -> datetime | None:
    row = await s.get(t.DomainThrottleRow, domain)
    return row.next_allowed_at if row else None


async def reserve_domain(s: AsyncSession, domain: str, interval_seconds: float) -> None:
    next_allowed = utcnow() + timedelta(seconds=interval_seconds)
    row = await s.get(t.DomainThrottleRow, domain)
    if row:
        row.next_allowed_at = next_allowed
    else:
        s.add(t.DomainThrottleRow(domain=domain, next_allowed_at=next_allowed))
    await s.commit()
