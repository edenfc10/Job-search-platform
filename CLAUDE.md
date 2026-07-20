# AIJAA — AI Job Applications Agent

Headless multi-tenant service that helps job seekers: adaptive profile intake →
bilingual resume (EN/HE) → job discovery + RAG matching → **human approval gate**
→ ATS tailoring → application filling → **pre-submit human validation** →
submission validation. Built to the vision/PRD in `../*-AI-Job-Search-Agent-*.md`.

Consumed by an external "operator client" (a recruiter's system) via REST + signed
webhooks. This reference build uses SQLite + in-process everything; the prompt-chain
playbook (`../AIJAA_Prompt_Chain.md`) documents the Postgres/Redis production target.

## Commands
`just setup | test | lint | demo | run | ci`  (or `.venv/bin/python -m pytest -q`)

## Architecture (pipeline with a human gate)
```
intake → profile(versioned) → master resume (en/he)
discovery(connectors) → matcher(RAG, 70 floor) → APPROVAL GATE(operator)
  → tailor(ATS) → analyze(how-to-apply) → executor(fill) → READY_TO_SUBMIT(human)
  → validate(receipts)
statuses: discovered→matched→approved→tailored→applying→ready_to_submit
          →[needs_human]→submitted→confirmed|failed   (core/status.py)
```

## Layout (`src/aijaa/`)
- `core/` — models (single source of truth), tables, status state machine, repo (tenancy-scoped), config, db
- `llm/` — protocols (`base.py`), deterministic fakes (`fakes.py`, default), Claude impl (`claude.py`), factory, usage
- `intake/` — rubric (code-scored completeness), adaptive interview engine
- `resume/` — IR, writer + fabrication guard, docx(RTL-aware)/txt renderers, deterministic ATS scorer, fact-safe tailor
- `discovery/` — JobSource connectors (greenhouse/lever/fixture), normalize/dedupe/freshness
- `matching/` — hashing embedder + cosine, hard filters, service (rerank + 70 floor withholding)
- `application/` — gate, fingerprint, forms (HTML parse + interrupt detect), answers (classify+resolve), analyzer, executor, validator, browser drivers, service
- `observability/` — signed webhooks (audit + LLM usage live in core/repo + tables)
- `testkit/` — in-process mock ATS (`mockboard.py`)
- `api/` — FastAPI routers (seekers, pipeline, approvals, applications)

## Non-negotiable invariants (from the PRD philosophy)
1. **Truthful only** — resume bullets & answers cite profile `fact_id`s; `resume/guard.py` is a hard gate (fabrications rejected → verbatim fallback).
2. **Human approval before any application** — `application/gate.require_approval`; no auto-approve flag exists.
3. **7/10 floor is a withholding rule** — `matching/service.py`: rerank < `settings.match_floor` (70) is withheld, never surfaced.
4. **Pre-submit human validation** — executor stops at `ready_to_submit`; real submit only via `confirm_submit` with `DRY_RUN=false`.
5. **No CAPTCHA/login/2FA/bot-wall bypass** — `forms.detect_interrupts` → `needs_human`, stop. Never solved.
6. **No double submit** — ambiguity after a submit click → `needs_human`, never a retry (`validator.retry_decision`).
7. **Tenant isolation** — all seeker data via `core/repo.py`, scoped by `seeker_id`.
8. **DRY_RUN defaults true**; fake LLMs default (`AIJAA_FAKE_LLM=true`) — tests/demo never spend API tokens.

## Conventions
- Domain shapes: `core/models.py` — reference, never restate.
- Status only changes via `repo.transition_application` (validates + timelines + audits).
- Every LLM call behind a protocol with a fake; Claude uses `claude-opus-4-8` (smart) / `claude-haiku-4-5` (extraction), adaptive thinking, structured outputs.

## State log
- After MVP+engine build (2026-07-16): intake→resume→discovery→matching→approval→handoff **and** analyzer→executor→validator complete; 36 tests green; `scripts/demo_pipeline.py` runs the whole flow on fakes. Pending: orchestration-lite, full audit/metrics surface, mockboard E2E test + eval gates (prompt-chain prompts 12–14).
- After QA Checkpoint #2 (2026-07-16): added SQLite-backed in-process orchestration (`orchestration/runner.py`, `pipeline.py`, `governor.py`) with idempotent task rows, dead letters, per-seeker/global browser caps, daily application caps, and per-domain pacing. Approval and human-input events now enqueue local tasks while direct QA endpoints remain supported. Observability now includes redacted structured logging, Prometheus text `/metrics`, seeker/global usage rollups, and merged chronological application timelines. `testkit/mockboard.py` serves a Greenhouse-shaped 20-job feed plus single/multi/CAPTCHA/flaky application flows. `README.md` documents operator runbook and DRY_RUN flip policy. `just ci` = lint + import/type smoke + full tests.
- OpenAI production mode (2026-07-16): `llm/openai_provider.py` implements the existing LLM protocols through the OpenAI Responses API with structured outputs. Enable with `AIJAA_FAKE_LLM=false`, `AIJAA_LLM_PROVIDER=openai`, and `AIJAA_OPENAI_API_KEY`. Defaults: fast=`gpt-5.6-terra`, smart=`gpt-5.6`. DRY_RUN remains independent and defaults true.
- Production operational mode (2026-07-20): `AIJAA_PRODUCTION_MODE=true` disables mock/sample paths in the UI, ignores fixture sources, and prevents local mockboard mounting. `/healthz` reports production readiness, missing requirements, configured sources, and apply driver. Real sources are Greenhouse/Lever config and manual URLs (`POST /v1/jobs/manual`); LinkedIn/Israeli boards require approved API/feed/manual URL workflows only. Use `scripts/check_production.py` before launch.
