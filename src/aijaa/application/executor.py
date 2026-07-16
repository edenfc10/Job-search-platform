"""Application executor. Fills the form from the ApplicationPlan, answers
generated fields (fact-guarded), then STOPS at the pre-submit human-validation
gate (ready_to_submit). Real submit only happens on explicit confirmation AND
DRY_RUN=false AND no unresolved needs_human items.

Interrupt detection (CAPTCHA / login / 2FA / bot walls) runs before every
action: on detection the executor captures evidence, escalates to needs_human,
and STOPS. No code path attempts to solve or bypass a challenge.

No-double-submit: ambiguity about whether a submit landed -> needs_human,
never an automatic retry of the click."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.application import gate
from aijaa.application.analyzer import ApplicationPlan
from aijaa.application.answers import resolve_auto
from aijaa.application.browser import PageDriver
from aijaa.application.fingerprint import ACCOUNT_REQUIRED
from aijaa.application.forms import detect_interrupts
from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord, Evidence
from aijaa.core.status import ApplicationStatus
from aijaa.llm.factory import get_llms
from aijaa.resume.guard import check_answer_text

log = structlog.get_logger()


class FillResult:
    def __init__(self, values: dict, files: dict, needs_human: list[dict]):
        self.values = values
        self.files = files
        self.needs_human = needs_human


async def _build_values(s: AsyncSession, app: ApplicationRecord, plan: ApplicationPlan) -> FillResult:
    profile = await repo.latest_profile(s, app.seeker_id)
    prefs = await repo.get_preferences(s, app.seeker_id)
    assert profile is not None and prefs is not None

    values: dict = {}
    files: dict = {}
    pending: list[dict] = []

    # Resume artifact to attach (tailored preferred).
    resume = None
    if app.resume_id:
        resume = await repo.get_resume(s, app.seeker_id, app.resume_id)
    if resume is None:
        resume = await repo.latest_master_resume(s, app.seeker_id, resume_language(prefs))
    resume_path = (resume.artifacts.get("docx") if resume else None)

    for pf in plan.fields:
        name = pf.field.name
        if pf.source.startswith("auto:"):
            values[name] = resolve_auto(pf.source.split(":", 1)[1], profile, prefs)
        elif pf.source == "attach_resume":
            if resume_path:
                files[name] = resume_path
        elif pf.source == "generate":
            # Human-supplied answer overrides generation if present.
            if name in app.human_answers:
                values[name] = app.human_answers[name]
                continue
            answer = await get_llms().answers.answer(pf.field.label or name, profile, prefs)
            if answer.needs_human or check_answer_text(answer.text, answer.fact_ids, profile):
                pending.append({"field": name, "question": pf.field.label or name,
                                "reason": answer.reason or "fabrication_guard"})
            else:
                values[name] = answer.text
        elif pf.source == "needs_human":
            if name in app.human_answers:
                values[name] = app.human_answers[name]
            else:
                pending.append({"field": name, "question": pf.field.label or name,
                                "reason": pf.reason})
        # 'skip' fields are intentionally omitted
    return FillResult(values, files, pending)


def resume_language(prefs) -> str:
    return prefs.resume_languages[0] if prefs.resume_languages else "en"


async def execute(
    s: AsyncSession, app: ApplicationRecord, driver: PageDriver, snapshot_stem: str
) -> ApplicationRecord:
    await gate.require_approval(s, app)
    settings = get_settings()
    plan = ApplicationPlan.model_validate(app.plan)

    if plan.platform in ACCOUNT_REQUIRED:
        app.needs_human_reason = "platform_requires_account"
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )

    # Enter 'applying' from tailored (fresh run) or needs_human (resumed after
    # human input). Already-applying is a re-entrant call — no transition.
    if app.status != ApplicationStatus.applying.value:
        app = await repo.transition_application(s, app, ApplicationStatus.applying.value, "system")

    # Re-check interrupts on the live page before touching anything.
    html = await driver.goto(plan.apply_url)
    interrupts = detect_interrupts(html)
    if interrupts:
        shot = await driver.snapshot(f"{snapshot_stem}_interrupt")
        app.evidence.append(Evidence(kind="screenshot", value=shot))
        app.needs_human_reason = ",".join(interrupts)
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )

    fill = await _build_values(s, app, plan)
    if fill.needs_human:
        app.pending_questions = fill.needs_human
        app.needs_human_reason = "pending_questions"
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system",
            f"{len(fill.needs_human)} question(s) need human input",
        )

    # Everything resolved: fill the form and capture the review packet, then STOP
    # at the pre-submit gate. Fill happens against a submit-suppressed action in
    # dry-run; in live mode we still stop here until a human confirms.
    review = {
        "values": {k: v for k, v in fill.values.items()},
        "attached": list(fill.files.keys()),
        "platform": plan.platform,
        "apply_url": plan.apply_url,
    }
    app.evidence.append(Evidence(kind="review_packet", value=str(review)))
    shot = await driver.snapshot(f"{snapshot_stem}_filled")
    app.evidence.append(Evidence(kind="screenshot", value=shot))
    app.plan = {**app.plan, "_fill": {"values": fill.values, "files": fill.files}}

    log.info("application_ready_to_submit", application_id=app.id, dry_run=settings.dry_run)
    return await repo.transition_application(
        s, app, ApplicationStatus.ready_to_submit.value, "system",
        "filled; awaiting human submit confirmation",
    )


async def confirm_submit(
    s: AsyncSession, app: ApplicationRecord, driver: PageDriver, confirmed_by: str,
    snapshot_stem: str,
) -> ApplicationRecord:
    """Called only after a human confirms. Performs the real submit when
    DRY_RUN=false; in dry-run it records the intended submit without clicking."""
    await gate.require_approval(s, app)
    settings = get_settings()
    plan = ApplicationPlan.model_validate(app.plan)
    fill = app.plan.get("_fill", {"values": {}, "files": {}})

    if settings.dry_run:
        app.evidence.append(Evidence(kind="dry_run", value="submit suppressed (DRY_RUN=true)"))
        return await repo.transition_application(
            s, app, ApplicationStatus.applying.value, f"operator:{confirmed_by}",
            "dry-run: submit suppressed, returned to applying",
        )

    from aijaa.application.validator import validate_submission

    try:
        html = await driver.submit_form(
            plan.form.action if plan.form else "", plan.form.method if plan.form else "post",
            fill["values"], fill["files"],
        )
    except Exception as e:  # noqa: BLE001 - ambiguous post-click state
        # We do NOT know if the submit landed. Never retry the click.
        app.needs_human_reason = f"possibly_submitted: {type(e).__name__}"
        shot = await driver.snapshot(f"{snapshot_stem}_ambiguous")
        app.evidence.append(Evidence(kind="screenshot", value=shot))
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )

    shot = await driver.snapshot(f"{snapshot_stem}_submitted")
    app.evidence.append(Evidence(kind="screenshot", value=shot))
    app = await repo.transition_application(
        s, app, ApplicationStatus.submitted.value, f"operator:{confirmed_by}", "submitted"
    )
    return await validate_submission(s, app, html)
