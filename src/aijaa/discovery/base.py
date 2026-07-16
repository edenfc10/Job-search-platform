from typing import Protocol

from pydantic import BaseModel


class SearchCriteria(BaseModel):
    keywords: list[str] = []
    locations: list[str] = []
    remote: bool | None = None
    posted_within_days: int = 21


class RawPosting(BaseModel):
    source: str
    url: str
    company: str
    title: str
    location: str | None = None
    remote: bool | None = None
    description_html_or_text: str = ""
    posted_at_iso: str | None = None
    salary_raw: str | None = None


class JobSource(Protocol):
    name: str

    async def fetch(self, criteria: SearchCriteria) -> list[RawPosting]: ...
