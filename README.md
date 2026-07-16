# AIJAA

AIJAA is a headless AI job-application agent for operator clients. It intakes a
job seeker's profile, generates truthful bilingual resumes, discovers and ranks
jobs, waits for per-job human approval, tailors the resume, fills applications,
stops at a pre-submit human gate, and validates receipts after an explicit submit
confirmation.

The reference build is intentionally lightweight: SQLite, deterministic fake LLMs
by default, and an in-process DB-backed task runner. The production target remains
Postgres/Redis/arq as documented in `../AIJAA_Prompt_Chain.md`.

## Architecture

```text
intake -> profile -> master resume
discovery -> matcher -> approval gate
approved -> local task queue -> tailor -> analyze -> fill -> ready_to_submit
human confirm -> submit when DRY_RUN=false -> validate -> confirmed|needs_human
```

Safety invariants are code-level defaults: `AIJAA_DRY_RUN=true`, fake LLMs unless
explicitly configured, no application without approval, no CAPTCHA/login bypass,
no retry after an ambiguous submit click, and match scores below 70 are withheld.

## Runbook

```bash
cd /Users/amitbakshi/AIJAA/aijaa
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
just ci
just demo
just run
```

The API serves `/healthz`, `/docs`, `/metrics`, and the `/v1/...` operator surface.
Use `AIJAA_DATABASE_URL` and `AIJAA_ARTIFACTS_DIR` to isolate environments.

## OpenAI Production Mode

Copy `.env.example` to `.env`, set `AIJAA_OPENAI_API_KEY`, and run the API:

```bash
cp .env.example .env
# edit .env with the real key
.venv/bin/uvicorn aijaa.api.app:app --host 127.0.0.1 --port 8000
```

Required settings:

- `AIJAA_FAKE_LLM=false`
- `AIJAA_LLM_PROVIDER=openai`
- `AIJAA_OPENAI_API_KEY=...`

Defaults:

- `AIJAA_OPENAI_MODEL_FAST=gpt-5.6-terra`
- `AIJAA_OPENAI_MODEL_SMART=gpt-5.6`

Keep `AIJAA_DRY_RUN=true` while using real models unless the production
submit-readiness checklist below is complete.

## Operator Flow

1. Create a seeker with `POST /v1/seekers`.
2. Run intake turns with `POST /v1/seekers/{id}/intake/turns`.
3. Build resumes with `POST /v1/seekers/{id}/resume`.
4. Run discovery and matching with `POST /v1/discovery/run` and
   `POST /v1/seekers/{id}/match/run`.
5. Review matches through `GET /v1/seekers/{id}/matches`.
6. Approve one job at a time with `POST /v1/matches/{id}/decision`.
7. Monitor `GET /v1/seekers/{id}/pipeline` and
   `GET /v1/applications/{id}/timeline`.
8. Resolve `needs_human` with `POST /v1/applications/{id}/human-input`.
9. Submit only from `ready_to_submit` using
   `POST /v1/applications/{id}/confirm-submit`.

The local queue is additive: direct run endpoints still exist for QA, while
approval and human-input events enqueue idempotent tasks for the in-process runner.

## Governance

Defaults:

- `AIJAA_APPLICATIONS_PER_DAY=10`
- `AIJAA_BROWSER_POOL_MAX=3`
- `AIJAA_DOMAIN_APPLICATION_INTERVAL_SECONDS=120`
- `AIJAA_DISCOVERY_INTERVAL_HOURS=6`

Tune these limits downward for sensitive boards or early production rollout.
Do not add per-seeker overrides that exceed global domain politeness.

## Needs Human

`needs_human` is a safe stop, not an error. Common reasons are CAPTCHA/login walls,
sensitive screening questions, unmapped required fields, and ambiguous submit
states. Operators should inspect `/timeline`, answer pending questions or resolve
the external state, then resume via the human-input endpoint.

## Observability

- JSON logs are redacted for configured PII/secret keys.
- Audit events are append-only and include status transitions, decisions, human
  input, submit events, and webhook attempts.
- `/metrics` returns Prometheus text metrics.
- `/v1/seekers/{id}/usage?window=30d` and `/v1/usage?window=30d` summarize LLM
  usage. Fake LLM mode records zero-cost deterministic behavior unless a live
  Claude run is explicitly configured.

## DRY_RUN Flip Policy

Code default remains `AIJAA_DRY_RUN=true`. Flip it per environment only after:

- `just ci` passes.
- Mock-board E2E and eval gates pass.
- Operator webhook/human-input staffing is live.
- Per-domain limits have been reviewed and, if anything, tuned downward.
- First-week monitoring owners are assigned for stalled applications,
  `needs_human` volume, webhook failures, and confirmation rates.
