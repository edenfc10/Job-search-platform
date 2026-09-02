"""Resume intermediate representation (IR). The IR is the canonical resume
content; renderers turn it into docx/txt. Every bullet cites the profile
fact_ids it was written from — the fabrication guard enforces this."""

from typing import Literal

from pydantic import BaseModel, Field

from aijaa.core.models import ProfessionalProfile, new_id


class Bullet(BaseModel):
    bullet_id: str = Field(default_factory=new_id)
    text: str
    fact_ids: list[str] = []


class ExperienceEntry(BaseModel):
    company: str
    title: str
    start: str
    end: str | None = None
    location: str | None = None
    bullets: list[Bullet] = []


class EducationEntry(BaseModel):
    institution: str
    degree: str = ""
    field: str = ""
    year: str | None = None


class ResumeIR(BaseModel):
    language: Literal["en", "he"] = "en"
    full_name: str = ""
    contact_line: str = ""
    summary: str = ""
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    skills: list[str] = []
    certifications: list[str] = []
    links: list[str] = []

    def all_bullets(self) -> list[Bullet]:
        return [b for e in self.experience for b in e.bullets]


def base_ir_from_profile(profile: ProfessionalProfile, language: str = "en") -> ResumeIR:
    """Deterministic skeleton IR (verbatim facts). Writers improve on this;
    it is also the safe fallback when generated bullets fail the guard."""
    contact_bits = [profile.contact.email, profile.contact.phone, profile.contact.location]
    return ResumeIR(
        language=language,  # type: ignore[arg-type]
        full_name=profile.contact.full_name,
        contact_line=" | ".join(b for b in contact_bits if b),
        experience=[
            ExperienceEntry(
                company=e.company,
                title=e.title,
                start=e.start,
                end=e.end,
                location=e.location,
                bullets=[Bullet(text=f.text, fact_ids=[f.fact_id]) for f in e.achievements],
            )
            for e in profile.work_history
        ],
        education=[
            EducationEntry(
                institution=ed.institution, degree=ed.degree, field=ed.field, year=ed.year
            )
            for ed in profile.education
        ],
        skills=[f.text for f in profile.skills],
        certifications=[f.text for f in profile.certifications],
        links=list(profile.contact.links),
    )
