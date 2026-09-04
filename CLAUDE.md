# AIJAA — AI Job Applications Agent

Headless multi-tenant service that helps job seekers: adaptive profile intake →
bilingual resume (EN/HE) → job discovery + RAG matching → **human approval gate**
→ ATS tailoring → application filling → **pre-submit human validation** →
submission validation. Built to the vision/PRD in `../*-AI-Job-Search-Agent-*.md`.

Consumed by an external "operator client" (a recruiter's system) via REST + signed
webhooks. The local build supports PostgreSQL/Alembic, Redis/ARQ worker foundations,
and SQLite-isolated tests; production authentication, tenancy, outbox delivery, and
infrastructure remain incomplete.

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

## Layout (`backend/src/aijaa/`)
- `core/` — models (single source of truth), tables, status state machine, repo (tenancy-scoped), config, db
- `llm/` — protocols (`base.py`), deterministic fakes (`fakes.py`, default), Claude impl (`claude.py`), factory, usage
- `intake/` — rubric (code-scored completeness), adaptive interview engine
- `resume/` — IR, writer + fabrication guard, docx(RTL-aware)/txt renderers, deterministic ATS scorer, fact-safe tailor
- `discovery/` — JobSource connectors (greenhouse/lever/fixture), normalize/dedupe/freshness
- `matching/` — hashing embedder + cosine, hard filters, service (rerank + 70 floor withholding)
- `application/` — gate, fingerprint, forms (HTML parse + interrupt detect), answers (classify+resolve), analyzer, executor, validator, browser drivers, service
- `observability/` — signed webhooks (audit + LLM usage live in core/repo + tables)
- `testkit/` — in-process mock ATS (`mockboard.py`)
- `api/` — FastAPI routers (seekers, pipeline, approvals, applications, tasks)
- `frontend/` — standalone static operator console served by FastAPI
- `backend/migrations/` — Alembic configuration and migrations
- `infrastructure/` — local service definitions

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
- After MVP+engine build (2026-07-16): intake→resume→discovery→matching→approval→handoff **and** analyzer→executor→validator complete; 36 tests green; `backend/scripts/demo_pipeline.py` runs the whole flow on fakes. Pending: orchestration-lite, full audit/metrics surface, mockboard E2E test + eval gates (prompt-chain prompts 12–14).
- After QA Checkpoint #2 (2026-07-16): added SQLite-backed in-process orchestration (`orchestration/runner.py`, `pipeline.py`, `governor.py`) with idempotent task rows, dead letters, per-seeker/global browser caps, daily application caps, and per-domain pacing. Approval and human-input events now enqueue local tasks while direct QA endpoints remain supported. Observability now includes redacted structured logging, Prometheus text `/metrics`, seeker/global usage rollups, and merged chronological application timelines. `testkit/mockboard.py` serves a Greenhouse-shaped 20-job feed plus single/multi/CAPTCHA/flaky application flows. `README.md` documents operator runbook and DRY_RUN flip policy. `just ci` = lint + import/type smoke + full tests.
- OpenAI production mode (2026-07-16): `llm/openai_provider.py` implements the existing LLM protocols through the OpenAI Responses API with structured outputs. Enable with `AIJAA_FAKE_LLM=false`, `AIJAA_LLM_PROVIDER=openai`, and `AIJAA_OPENAI_API_KEY`. Defaults: fast=`gpt-4.1-mini`, smart=`gpt-4.1`. DRY_RUN remains independent and defaults true.
- Production operational mode (2026-07-20): `AIJAA_PRODUCTION_MODE=true` disables mock/sample paths in the UI, ignores fixture sources, and prevents local mockboard mounting. `/healthz` reports production readiness, missing requirements, configured sources, and apply driver. Real sources are Greenhouse/Lever config and manual URLs (`POST /v1/jobs/manual`); LinkedIn/Israeli boards require approved API/feed/manual URL workflows only. Use `backend/scripts/check_production.py` before launch.
- Post-Codex audit fixes (2026-07-30): the orchestration runner (`orchestration/runner.py`/`pipeline.py`/`governor.py`) is built but **still not invoked by anything running** (no lifespan hook, script, or scheduler drains it) — approving a match only queues a task; direct QA endpoints in `api/routers/applications.py` remain the only way anything executes. Fixed three concrete bugs found by live-testing rather than static review: (1) `governor.can_start_browser_task` counted a task's own newly-`"running"` row as evidence it couldn't start, so every `run_analyze`/`run_apply`/`resume_after_human` task would self-block and eventually dead-letter — fixed via `exclude_task_id` threaded through `repo.active_browser_tasks` → `governor.can_start_browser_task` → `runner._execute_task`; (2) `applications.py`'s `human_input()` both resumed execution synchronously *and* enqueued a duplicate `resume_after_human` task — removed the redundant enqueue; (3) fabricated OpenAI model IDs (`gpt-5.6`, `gpt-5.6-terra`) replaced with real ones (`gpt-4.1`, `gpt-4.1-mini`) in `config.py`, `.env.example`, and `README.md` — flagged as unverified against a live catalog, unlike the Claude model strings. Still open: wire the runner into something that actually drains it; `current_seeker_id` unset inside the runner (usage misattribution once wired); `retry_decision` never called from production code (executor's hardcoded fallback is safe but undocumented-by-that-function); no real E2E proving the mock board's seeded feed round-trips through `GreenhouseBoardSource`; one placeholder test in `test_orchestration.py`.
- Local stabilization checkpoint (2026-08-24): CV interpretation moved server-side in demo mode; fixture dates and local mock-form URLs are runtime-relative; the console disables static caching and restores seeker/match state; form preparation fills before review and submit reopens/refills in a fresh driver; placeholder profiles and profile-version drift stop at `needs_human`; resume artifacts track profile versions; generic role words no longer create high fake-match scores; direct synchronous stages supersede queued local tasks. Verification target is 74 tests plus Ruff and JavaScript syntax. Production blockers remain auth/organizations, Postgres/Alembic, Redis/arq/outbox, hardened uploads/manual URLs, S3, CI/CD, AWS, and the versioned/idempotent submission-attempt contract.
- Local MVP completion (2026-08-26): deterministic CV interpretation now handles multi-role English CVs, Hebrew section headings, month-level employment dates, structured education, target titles, salary, and contextual dealbreakers. The console renders `pending_questions`, posts human answers, restores the human gate after refresh, and was manually verified through `ready_to_submit` plus `dry_run_submit_suppressed`. Completeness rounding now yields 100 for a complete profile. `AIJAA_WORKFLOW_MODE=sync` is the explicit local default, so approvals no longer create orphaned task rows; the reference queue remains opt-in. Verification target is 79 tests plus Ruff and JavaScript syntax.
