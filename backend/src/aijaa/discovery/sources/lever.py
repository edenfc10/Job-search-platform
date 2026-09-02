"""Lever public postings API connector (official endpoint, no scraping)."""

from datetime import UTC, datetime

import httpx

from aijaa.discovery.base import RawPosting, SearchCriteria


class LeverPostingsSource:
    name = "lever"

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
                    f"https://api.lever.co/v0/postings/{org}", params={"mode": "json"}
                )
                if resp.status_code != 200:
                    continue
                for job in resp.json():
                    created_ms = job.get("createdAt")
                    posted = (
                        datetime.fromtimestamp(created_ms / 1000, UTC).isoformat()
                        if created_ms
                        else None
                    )
                    out.append(
                        RawPosting(
                            source=self.name,
                            url=job.get("hostedUrl", ""),
                            company=org,
                            title=job.get("text", ""),
                            location=(job.get("categories") or {}).get("location"),
                            description_html_or_text=job.get("description", ""),
                            posted_at_iso=posted,
                        )
                    )
        finally:
            if owns_client:
                await client.aclose()
        return out
