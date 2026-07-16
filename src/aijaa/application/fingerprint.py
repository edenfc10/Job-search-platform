"""ATS platform fingerprinting — table-driven, URL patterns first, DOM markers
second. Platforms that require candidate accounts route to needs_human by
policy (no automated account creation)."""

import re

URL_PATTERNS: list[tuple[str, str]] = [
    (r"boards\.greenhouse\.io|greenhouse\.io/.+/jobs", "greenhouse"),
    (r"jobs\.lever\.co", "lever"),
    (r"\.ashbyhq\.com|jobs\.ashbyhq\.com", "ashby"),
    (r"myworkdayjobs\.com|workday\.com", "workday"),
    (r"taleo\.net", "taleo"),
    (r"icims\.com", "icims"),
    (r"smartrecruiters\.com", "smartrecruiters"),
    (r"^mailto:", "email_apply"),
]

DOM_MARKERS: list[tuple[str, str]] = [
    ("greenhouse", "greenhouse"),
    ("lever-", "lever"),
    ("ashby", "ashby"),
    ("workday", "workday"),
    ("taleo", "taleo"),
    ("icims", "icims"),
    ("smartrecruiters", "smartrecruiters"),
]

ACCOUNT_REQUIRED = {"workday", "taleo", "icims"}


def fingerprint(url: str, html: str = "") -> str:
    for pattern, platform in URL_PATTERNS:
        if re.search(pattern, url, re.I):
            return platform
    lowered = html.lower()
    for marker, platform in DOM_MARKERS:
        if marker in lowered:
            return platform
    if "<form" in lowered:
        return "custom_form"
    return "unknown"
