"""Application analyzer — read-only reconnaissance BEFORE any filling.
Fingerprints the platform, extracts the form schema, classifies every field,
computes plan confidence, and persists the ApplicationPlan. Never types,
never logs in, never submits."""

from pydantic import BaseModel

from aijaa.application import gate
from aijaa.application.answers import PlannedField, classify_field
from aijaa.application.browser import PageDriver
from aijaa.application.fingerprint import ACCOUNT_REQUIRED, fingerprint
from aijaa.application.forms import FormSchema, detect_interrupts, extract_form
from aijaa.core import repo
from aijaa.core.models import ApplicationRecord, Evidence
from aijaa.core.status import ApplicationStatus


class ApplicationPlan(BaseModel):
    platform: str
    apply_url: str
    form: FormSchema | None = None
    fields: list[PlannedField] = []
    blockers: list[str] = []
    confidence: str = "low"  # high | medium | low
    needs_human_fields: list[str] = []


def _confidence(fields: list[PlannedField]) -> str:
    required = [f for f in fields if f.field.required]
    if not required:
        required = fields
    if not required:
        return "low"
    mapped = [f for f in required if f.source.startswith(("auto:", "generate", "attach_resume"))]
    coverage = len(mapped) / len(required)
    if coverage >= 0.8:
        return "high"
    if coverage >= 0.5:
        return "medium"
    return "low"


async def analyze(s, app: ApplicationRecord, driver: PageDriver, snapshot_path: str) -> ApplicationRecord:
    await gate.require_approval(s, app)
    posting = await repo.get_posting(s, app.posting_id)
    assert posting is not None
    apply_url = posting.apply_url or posting.canonical_url

    html = await driver.goto(apply_url)
    shot = await driver.snapshot(snapshot_path)
    app.evidence.append(Evidence(kind="screenshot", value=shot))

    platform = fingerprint(apply_url, html)
    blockers = detect_interrupts(html)
    if platform in ACCOUNT_REQUIRED:
        blockers.append("platform_requires_account")

    plan = ApplicationPlan(platform=platform, apply_url=apply_url, blockers=blockers)
    if "posting_closed" in blockers:
        app.plan = plan.model_dump()
        return await repo.transition_application(
            s, app, ApplicationStatus.failed.value, "system", "posting_closed"
        )
    if blockers:
        app.plan = plan.model_dump()
        app.needs_human_reason = ",".join(blockers)
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )

    form = extract_form(html)
    if form is None:
        app.plan = plan.model_dump()
        app.needs_human_reason = "no_parseable_form"
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )

    plan.form = form
    plan.fields = [classify_field(f) for f in form.fields]
    plan.needs_human_fields = [
        f.field.name for f in plan.fields if f.source == "needs_human"
    ]
    plan.confidence = _confidence(plan.fields)
    app.plan = plan.model_dump()
    await repo.save_application(s, app)
    await repo.audit(
        s, app.seeker_id, "application", app.id, "plan_created", "system",
        {"platform": platform, "confidence": plan.confidence,
         "needs_human_fields": plan.needs_human_fields},
    )
    if plan.confidence == "low":
        app.needs_human_reason = "low_confidence_plan"
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )
    return app
