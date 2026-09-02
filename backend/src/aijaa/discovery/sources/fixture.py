"""Fixture source: reads postings from local JSON files. Used by tests, demos,
and QA runs — no network access."""

import json
import os
from datetime import UTC, datetime, timedelta

from aijaa.discovery.base import RawPosting, SearchCriteria


class FixtureSource:
    name = "fixture"

    def __init__(self, directory: str):
        self.directory = directory

    async def fetch(self, criteria: SearchCriteria) -> list[RawPosting]:
        out: list[RawPosting] = []
        if not os.path.isdir(self.directory):
            return out
        for fname in sorted(os.listdir(self.directory)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(self.directory, fname), encoding="utf-8") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for item in items:
                payload = dict(item)
                days_ago = payload.get("posted_days_ago")
                if days_ago is not None:
                    payload["posted_at_iso"] = (
                        datetime.now(UTC) - timedelta(days=max(0, int(days_ago)))
                    ).isoformat()
                out.append(RawPosting.model_validate(payload))
        return out
