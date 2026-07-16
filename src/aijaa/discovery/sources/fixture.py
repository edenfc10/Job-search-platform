"""Fixture source: reads postings from local JSON files. Used by tests, demos,
and QA runs — no network access."""

import json
import os

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
            out.extend(RawPosting.model_validate(item) for item in items)
        return out
