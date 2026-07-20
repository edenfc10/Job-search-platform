"""RawPosting -> JobPosting: canonical URL, HTML stripping, salary parsing,
content hash, freshness handling."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from aijaa.core.config import get_settings
from aijaa.core.models import JobPosting
from aijaa.discovery.base import RawPosting

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                    "gh_src", "lever-source", "ref", "src"}
_TAG_RE = re.compile(r"<[^>]+>")
_SALARY_RE = re.compile(
    r"(?:[$₪€£]|USD|ILS|EUR|GBP)\s?(\d{2,3}(?:,\d{3})+|\d{4,6})(?:k)?"
    r"(?:\s*[-–to]+\s*(?:[$₪€£]|USD|ILS|EUR|GBP)?\s?(\d{2,3}(?:,\d{3})+|\d{4,6})(?:k)?)?",
    re.I,
)


def canonical_url(url: str) -> str:
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    return urlunparse(
        (parts.scheme or "https", parts.netloc.lower(), parts.path.rstrip("/"), "",
         urlencode(query), "")
    )


def strip_html(text: str) -> str:
    no_tags = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", no_tags).replace("&amp;", "&").replace("&nbsp;", " ").strip()


def parse_salary(text: str) -> tuple[int | None, int | None]:
    m = _SALARY_RE.search(text or "")
    if not m:
        return None, None

    def to_int(raw: str | None) -> int | None:
        if raw is None:
            return None
        n = int(raw.replace(",", ""))
        return n * 1000 if n < 1000 else n

    return to_int(m.group(1)), to_int(m.group(2))


def normalize(raw: RawPosting, posted_within_days: int) -> JobPosting | None:
    """Returns None when the posting is too stale to keep."""
    description = strip_html(raw.description_html_or_text)
    posted_at = None
    inferred = False
    if raw.posted_at_iso:
        try:
            posted_at = datetime.fromisoformat(raw.posted_at_iso.replace("Z", "+00:00"))
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=UTC)
        except ValueError:
            posted_at = None
    if posted_at is None:
        posted_at = datetime.now(UTC)
        inferred = True
    if datetime.now(UTC) - posted_at > timedelta(days=posted_within_days):
        return None

    salary_min, salary_max = parse_salary(raw.salary_raw or description)
    url = canonical_url(raw.url)
    apply_url = url
    if raw.source == "fixture" and not get_settings().production_mode:
        form = "multi" if "datastream" in raw.company.lower() else "single"
        apply_url = f"{get_settings().public_base_url.rstrip('/')}/mockboard/forms/{form}"
    return JobPosting(
        source=raw.source,
        canonical_url=url,
        apply_url=apply_url,
        company=raw.company,
        title=raw.title.strip(),
        location=raw.location,
        remote=raw.remote if raw.remote is not None else ("remote" in description.lower()[:2000] or None),
        salary_min=salary_min,
        salary_max=salary_max,
        description_text=description,
        posted_at=posted_at,
        posted_at_inferred=inferred,
        content_hash=hashlib.sha256(description.encode()).hexdigest()[:32],
    )
