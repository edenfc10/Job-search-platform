"""Application-engine orchestration for a single approved application:
tailor -> analyze -> execute (fill, stop at ready_to_submit). Human steps
(submit confirmation, answering pending questions) re-enter via dedicated
functions."""

import os

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.application import gate
from aijaa.application.analyzer import analyze
from aijaa.application.browser import get_driver
from aijaa.application.executor import confirm_submit, execute, resume_language
from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord
from aijaa.core.status import ApplicationStatus
from aijaa.resume.service import build_master_resume
from aijaa.resume.tailor import tailor_resume


def _stem(app: ApplicationRecord, tag: str) -> str:
    d = os.path.join(get_settings().artifacts_dir, app.seeker_id, "applications")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{app.id[:8]}_{tag}")


async def _current_master(s: AsyncSession, app: ApplicationRecord):
    profile = await repo.latest_profile(s, app.seeker_id)
    prefs = await repo.get_preferences(s, app.seeker_id)
    if profile is None:
        raise ValueError("no candidate profile")
    lang = resume_language(prefs) if prefs else "en"
    master = await repo.latest_master_resume(s, app.seeker_id, lang)
    if master is None or master.profile_version != profile.version:
        master = await build_master_resume(s, app.seeker_id, lang)
    return master


async def _refresh_tailored_resume(s: AsyncSession, app: ApplicationRecord) -> ApplicationRecord:
    """Rebuild artifacts when the editable profile changed after tailoring."""
    profile = await repo.latest_profile(s, app.seeker_id)
    current = (
        await repo.get_resume(s, app.seeker_id, app.resume_id) if app.resume_id else None
    )
    if profile is not None and current is not None and current.profile_version == profile.version:
        return app
    master = await _current_master(s, app)
    posting = await repo.get_posting(s, app.posting_id)
    if posting is None:
        raise ValueError("posting not found")
    doc, _report = await tailor_resume(s, app.seeker_id, posting, master)
    app.resume_id = doc.id
    await repo.save_application(s, app)
    return app


async def tailor_for_application(s: AsyncSession, app: ApplicationRecord) -> ApplicationRecord:
    await gate.require_approval(s, app)
    await repo.complete_queued_tasks_for_application(s, app.id, {"run_tailor"})
    if app.status in {
        ApplicationStatus.tailored.value,
        ApplicationStatus.applying.value,
        ApplicationStatus.ready_to_submit.value,
        ApplicationStatus.needs_human.value,
    }:
        return await _refresh_tailored_resume(s, app)
    if app.status in {
        ApplicationStatus.submitted.value,
        ApplicationStatus.confirmed.value,
    }:
        return app
    if app.status != ApplicationStatus.approved.value:
        raise ValueError(f"application is {app.status}, not approved/tailorable")
    master = await _current_master(s, app)
    posting = await repo.get_posting(s, app.posting_id)
    assert posting is not None
    doc, _report = await tailor_resume(s, app.seeker_id, posting, master)
    app.resume_id = doc.id
    return await repo.transition_application(
        s, app, ApplicationStatus.tailored.value, "system", "tailored for job"
    )


async def run_application(
    s: AsyncSession, application_id: str, driver=None
) -> ApplicationRecord:
    """Approved -> tailored -> analyzed -> filled (stops at ready_to_submit or
    needs_human). Idempotent-ish: safe to call from the approved state."""
    app = await repo.get_application(s, application_id)
    if app is None:
        raise ValueError("application not found")
    await repo.complete_queued_tasks_for_application(s, application_id, {"run_tailor"})
    own_driver = driver is None
    driver = driver or get_driver()
    tailored = ApplicationStatus.tailored.value
    try:
        if app.status == ApplicationStatus.approved.value:
            app = await tailor_for_application(s, app)
        # analyze() keeps status at 'tailored' on success, or advances it to
        # needs_human / failed on a blocker — only proceed to fill on success.
        if app.status == tailored:
            app = await analyze(s, app, driver, _stem(app, "analyze") + ".html")
        if app.status == tailored:
            app = await execute(s, app, driver, _stem(app, "fill"))
        elif app.status == ApplicationStatus.applying.value and app.plan:
            app = await _refresh_tailored_resume(s, app)
            app = await execute(s, app, driver, _stem(app, "fill"))
        elif app.status == ApplicationStatus.ready_to_submit.value and app.plan:
            app = await _refresh_tailored_resume(s, app)
            app = await repo.transition_application(
                s, app, ApplicationStatus.applying.value, "operator", "review rebuilt"
            )
            app = await execute(s, app, driver, _stem(app, "fill"))
        elif app.status == ApplicationStatus.needs_human.value and app.plan:
            app = await _refresh_tailored_resume(s, app)
            app = await execute(s, app, driver, _stem(app, "fill"))
        elif app.status in {
            ApplicationStatus.discovered.value,
            ApplicationStatus.matched.value,
            ApplicationStatus.failed.value,
            ApplicationStatus.confirmed.value,
        }:
            raise ValueError(f"application is {app.status}, not runnable")
        return app
    finally:
        if own_driver:
            await driver.close()


async def provide_human_input(
    s: AsyncSession, application_id: str, answers: dict[str, str], provided_by: str, driver=None
) -> ApplicationRecord:
    app = await repo.get_application(s, application_id)
    if app is None:
        raise ValueError("application not found")
    await repo.complete_queued_tasks_for_application(s, application_id, {"run_tailor"})
    app.human_answers.update(answers)
    app.pending_questions = [
        q for q in app.pending_questions if q["field"] not in answers
    ]
    await repo.save_application(s, app)
    await repo.audit(
        s, app.seeker_id, "application", app.id, "human_input_provided",
        f"operator:{provided_by}", {"fields": list(answers.keys())},
    )
    app = await _refresh_tailored_resume(s, app)
    # Re-enter execution; execute() moves needs_human -> applying itself.
    own_driver = driver is None
    driver = driver or get_driver()
    try:
        return await execute(s, app, driver, _stem(app, "fill"))
    finally:
        if own_driver:
            await driver.close()


async def confirm_and_submit(
    s: AsyncSession, application_id: str, confirmed_by: str, driver=None
) -> ApplicationRecord:
    app = await repo.get_application(s, application_id)
    if app is None:
        raise ValueError("application not found")
    if app.status != ApplicationStatus.ready_to_submit.value:
        raise ValueError(f"application is {app.status}, not ready_to_submit")
    own_driver = driver is None
    driver = driver or get_driver()
    try:
        return await confirm_submit(s, app, driver, confirmed_by, _stem(app, "submit"))
    finally:
        if own_driver:
            await driver.close()
