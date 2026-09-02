from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIJAA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./aijaa.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    artifacts_dir: str = "./artifacts"
    public_base_url: str = "http://127.0.0.1:8000"
    production_mode: bool = False
    # The local console calls compatibility endpoints synchronously. Set queue
    # only when a separately managed worker is actually draining task rows.
    workflow_mode: Literal["sync", "queue"] = "sync"

    llm_provider: str = "fake"  # fake | openai | anthropic
    openai_api_key: str = ""
    # NOTE: verify against OpenAI's current model catalog before enabling —
    # unlike the Claude model strings above, these aren't pinned against a
    # live-verified reference and should be reconfirmed at deploy time.
    openai_model_fast: str = "gpt-4.1-mini"
    openai_model_smart: str = "gpt-4.1"

    anthropic_api_key: str = ""
    # When true (default), all LLM protocols use deterministic fakes — no API usage.
    fake_llm: bool = True
    model_fast: str = "claude-haiku-4-5"  # lightweight extraction only
    model_smart: str = "claude-opus-4-8"  # judgment-heavy: rerank, writing, tailoring

    # Safety: the executor never clicks a real submit while true.
    dry_run: bool = True
    # "http" (plain HTML forms, mockboard, QA) or "playwright" (real browser).
    apply_driver: str = "http"
    enable_fixture_sources: bool = True
    enable_manual_urls: bool = True
    greenhouse_orgs: str = ""
    lever_orgs: str = ""
    israeli_partner_sources: str = ""  # comma list of permissioned partner/feed names
    linkedin_approved_access: bool = False

    operator_webhook_url: str = ""
    webhook_signing_secret: str = "dev-secret-change-me"

    # Product invariants (Vision/PRD)
    match_floor: int = 70  # matches below this are withheld, never surfaced
    match_top_n: int = 25
    rerank_top_k: int = 40
    posted_within_days: int = 21
    profile_stale_days: int = 90
    applications_per_day: int = 10

    # Local orchestration / politeness defaults. The reference build uses an
    # in-process DB-backed runner; these names map directly to the production
    # Redis/arq governor described in the prompt chain.
    browser_pool_max: int = 3
    domain_application_interval_seconds: float = 120.0
    discovery_interval_hours: int = 6
    domain_min_interval_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
