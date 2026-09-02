"""Greenhouse public board API connector (official endpoint, no scraping)."""

import httpx

from aijaa.discovery.base import RawPosting, SearchCriteria


class GreenhouseBoardSource:
    name = "greenhouse"

    def __init__(self, orgs: list[str], client: httpx.AsyncClient | None = None):
        self.orgs = orgs
        self.client = client

    async def fetch(self, criteria: SearchCriteria) -> list[RawPosting]:
        out: list[RawPosting] = []
        client = self.client or httpx.AsyncClient(timeout=20)
        owns_client = self.client is None
        try:
            for org in self.orgs:
                resp = await client.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs",
                    params={"content": "true"},
                )
                if resp.status_code != 200:
                    continue
                for job in resp.json().get("jobs", []):
                    out.append(
                        RawPosting(
                            source=self.name,
                            url=job.get("absolute_url", ""),
                            company=org,
                            title=job.get("title", ""),
                            location=(job.get("location") or {}).get("name"),
                            description_html_or_text=job.get("content", ""),
                            posted_at_iso=job.get("updated_at") or job.get("first_published"),
                        )
                    )
        finally:
            if owns_client:
                await client.aclose()
        return out
