"""Production readiness checks and source configuration helpers."""

import importlib.util

from pydantic import BaseModel

from aijaa.core.config import Settings


def csv_items(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


class ProductionStatus(BaseModel):
    production_mode: bool
    production_ready: bool
    missing_requirements: list[str]
    configured_sources: list[str]
    apply_driver: str
    warnings: list[str] = []


def configured_sources(settings: Settings) -> list[str]:
    sources: list[str] = []
    if csv_items(settings.greenhouse_orgs):
        sources.append("greenhouse")
    if csv_items(settings.lever_orgs):
        sources.append("lever")
    if settings.enable_manual_urls:
        sources.append("manual_urls")
    for partner in csv_items(settings.israeli_partner_sources):
        sources.append(f"israeli_partner:{partner}")
    if settings.linkedin_approved_access:
        sources.append("linkedin_approved")
    if settings.enable_fixture_sources and not settings.production_mode:
        sources.append("fixtures")
    return sources


def production_status(settings: Settings) -> ProductionStatus:
    missing: list[str] = []
    warnings: list[str] = []

    if settings.production_mode:
        if settings.fake_llm:
            missing.append("AIJAA_FAKE_LLM=false")
        if settings.llm_provider.lower() != "openai":
            missing.append("AIJAA_LLM_PROVIDER=openai")
        if not settings.openai_api_key:
            missing.append("AIJAA_OPENAI_API_KEY")
        if settings.apply_driver != "playwright":
            missing.append("AIJAA_APPLY_DRIVER=playwright")
        elif importlib.util.find_spec("playwright") is None:
            missing.append("playwright package: install with .venv/bin/pip install -e '.[apply]'")
        real_sources = [
            s for s in configured_sources(settings)
            if s not in {"fixtures"} and not s.startswith("israeli_partner:")
        ]
        if not real_sources and not csv_items(settings.israeli_partner_sources):
            missing.append("at least one real source: manual URLs, Greenhouse, Lever, or partner feed")
        if settings.enable_fixture_sources:
            warnings.append("fixture sources are ignored in production mode")
        if not settings.dry_run:
            warnings.append("live submit enabled; confirm human review staffing and domain limits")

    return ProductionStatus(
        production_mode=settings.production_mode,
        production_ready=not missing,
        missing_requirements=missing,
        configured_sources=configured_sources(settings),
        apply_driver=settings.apply_driver,
        warnings=warnings,
    )
