"""Resume build service: profile -> guarded IR -> artifacts -> persisted
ResumeDocument."""

import os

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ResumeDocument
from aijaa.resume.ir import ResumeIR
from aijaa.resume.render.docx import render_docx
from aijaa.resume.render.txt import render_txt
from aijaa.resume.writer import write_master_ir


def _artifact_dir(seeker_id: str) -> str:
    d = os.path.join(get_settings().artifacts_dir, seeker_id)
    os.makedirs(d, exist_ok=True)
    return d


def render_artifacts(ir: ResumeIR, seeker_id: str, stem: str) -> dict[str, str]:
    d = _artifact_dir(seeker_id)
    return {
        "docx": render_docx(ir, os.path.join(d, f"{stem}.docx")),
        "txt": render_txt(ir, os.path.join(d, f"{stem}.txt")),
    }


async def build_master_resume(
    s: AsyncSession, seeker_id: str, language: str = "en"
) -> ResumeDocument:
    profile = await repo.latest_profile(s, seeker_id)
    if profile is None:
        raise ValueError("no profile for seeker")
    ir = await write_master_ir(profile, language)
    doc = ResumeDocument(
        seeker_id=seeker_id,
        kind="master",
        language=language,
        profile_version=profile.version,
        ir=ir.model_dump(),  # type: ignore[arg-type]
    )
    doc.artifacts = render_artifacts(ir, seeker_id, f"master_{language}_{doc.id[:8]}")
    await repo.save_resume(s, doc)
    await repo.audit(s, seeker_id, "resume", doc.id, "master_resume_built", "system",
                     {"language": language})
    return doc
