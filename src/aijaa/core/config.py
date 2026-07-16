from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AIJAA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./aijaa.db"
    artifacts_dir: str = "./artifacts"

    anthropic_api_key: str = ""
    # When true (default), all LLM protocols use deterministic fakes — no API usage.
    fake_llm: bool = True
    model_fast: str = "claude-haiku-4-5"  # lightweight extraction only
    model_smart: str = "claude-opus-4-8"  # judgment-heavy: rerank, writing, tailoring

    # Safety: the executor never clicks a real submit while true.
    dry_run: bool = True
    # "http" (plain HTML forms, mockboard, QA) or "playwright" (real browser).
    apply_driver: str = "http"

    operator_webhook_url: str = ""
    webhook_signing_secret: str = "dev-secret-change-me"

    # Product invariants (Vision/PRD)
    match_floor: int = 70  # matches below this are withheld, never surfaced
    match_top_n: int = 25
    rerank_top_k: int = 40
    posted_within_days: int = 21
    profile_stale_days: int = 90
    applications_per_day: int = 10

    # Politeness
    domain_min_interval_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
