# AIJAA

AIJAA is an operator-driven job application workflow. It turns a candidate CV
into a reviewed professional profile, generates traceable resume artifacts,
discovers and ranks jobs, tailors a resume for an approved role, prepares an
application form, and stops at an explicit human confirmation gate before any
submission.

The current repository is a stable **local MVP**, not a production deployment.
It proves the workflow safely with deterministic fake LLMs, local fixtures,
PostgreSQL or SQLite, local artifacts, a mock ATS, and `DRY_RUN=true`.

> [!WARNING]
> The API currently has no authentication or organization isolation. Do not
> expose it to the public internet or process real candidate data on a shared
> host. Keep `AIJAA_DRY_RUN=true`; real external submission is not certified.

## Current status

| Area | Status | Notes |
|---|---|---|
| CV upload and text extraction | Working locally | PDF, DOCX, TXT, Markdown, and JSON |
| Editable candidate profile | Working locally | Versioned facts and career preferences |
| English CV interpretation | Working locally | Multi-role CVs and month-level dates |
| Hebrew CV interpretation | Partial | Hebrew section headings are supported |
| Resume generation | Working locally | DOCX/TXT with fact references |
| Hebrew resume generation | Partial | RTL layout exists; fake mode does not translate body content |
| Job discovery | Working locally | Fixtures plus Greenhouse/Lever connector code |
| Matching and filtering | Working locally | Freshness, dealbreakers, score floor, rationale, risks |
| Human approval | Working locally | Required before tailoring or preparation |
| Tailored resume | Working locally | Restricted to supported candidate facts |
| Human questions | Working locally | Resolved in the web console without curl |
| Application preparation | Proven against mock ATS | Stops at `ready_to_submit` |
| Real browser application | Not certified | Playwright exists, but real ATS flows are not release-ready |
| Real submission | Disabled | The verified path uses `DRY_RUN=true` |
| Authentication and tenancy | Not implemented | Production blocker |
| PostgreSQL and Alembic | Working locally | PostgreSQL 16, reversible initial migration, startup head check |
| Redis and ARQ worker | Foundation working locally | Worker, exact task claiming, lifecycle checks, and task status API; business endpoints remain synchronous |
| S3 and AWS | Not implemented | Production blocker |

Current verification baseline:

```text
92 tests passed
Ruff passed
JavaScript syntax passed
PostgreSQL upgrade/downgrade/upgrade passed on an isolated database
FastAPI queue-mode startup and ARQ worker startup passed against local Redis
Manual local flow reached ready_to_submit and dry_run_submit_suppressed
```

## Product workflow

```mermaid
flowchart LR
    A[Upload or paste CV] --> B[Extract text]
    B --> C[Interpret editable profile]
    C --> D{Human profile review}
    D -->|Save| E[Versioned candidate profile]
    E --> F[Generate master resumes]
    E --> G[Discover jobs]
    G --> H[Filter and rank]
    H --> I{Operator approval}
    I -->|Reject| J[Stop]
    I -->|Approve| K[Tailor resume]
    K --> L[Analyze application form]
    L --> M{Human input required?}
    M -->|Yes| N[Answer sensitive or unsupported questions]
    N --> L
    M -->|No| O[Fill and capture review packet]
    O --> P[ready_to_submit]
    P --> Q{Explicit human confirmation}
    Q -->|DRY_RUN=true| R[Record suppression; no external click]
    Q -->|Certified live mode only| S[Submit and validate receipt]
```

### What happens at each stage

1. **CV parsing** extracts text from an uploaded document. Nothing is persisted
   as a candidate until the operator reviews and saves the interpreted draft.
2. **Interpretation** creates two editable structures: verified candidate facts
   and search preferences. The local parser is conservative and may require
   manual correction for unusual CV layouts.
3. **Intake** stores a new profile version and calculates deterministic
   completeness. Required search fields gate downstream actions.
4. **Resume generation** builds an intermediate representation (IR), links
   bullets to candidate `fact_id` values, and renders DOCX/TXT artifacts.
5. **Discovery** loads jobs from configured sources, canonicalizes URLs, removes
   stale or duplicate records, and persists normalized postings.
6. **Matching** applies hard filters and reranking. Scores below the configured
   floor are withheld rather than presented as weak recommendations.
7. **Approval** is an attributable, immutable per-job decision. An application
   cannot advance without it.
8. **Tailoring** reorders and rewrites supported content for the selected job.
   Fabricated claims are rejected by the fact guard.
9. **Application analysis** fingerprints the platform, extracts form fields,
   detects blockers, and creates an application plan before filling anything.
10. **Human input** handles salary, legal, clearance, demographic, CAPTCHA,
    login, and unsupported questions without guessing or bypassing controls.
11. **Preparation** fills the approved values, attaches the tailored resume,
    captures evidence, and stops at `ready_to_submit`.
12. **Confirmation** is a separate human gate. Under `DRY_RUN=true`, AIJAA
    records `dry_run_submit_suppressed` and performs no external submit click.

## Runtime architecture

```mermaid
flowchart TB
    UI[Vanilla HTML/CSS/JavaScript console]
    API[FastAPI API]
    DB[(PostgreSQL / SQLite)]
    REDIS[(Redis delivery queue)]
    WORKER[ARQ worker]
    FS[(Local artifact directory)]
    LLM[Fake / OpenAI / Anthropic providers]
    SOURCES[Fixtures / Greenhouse / Lever / Manual URL]
    DRIVER[HTTP form driver / Playwright]
    MOCK[Local mock ATS]

    UI --> API
    API --> DB
    API --> REDIS
    REDIS --> WORKER
    WORKER --> DB
    API --> FS
    API --> LLM
    API --> SOURCES
    API --> DRIVER
    DRIVER --> MOCK
```

The local console uses `AIJAA_WORKFLOW_MODE=sync`. Button actions call the
compatibility endpoints directly and do not create orphaned background task
rows. `AIJAA_WORKFLOW_MODE=queue` now opens and verifies Redis during FastAPI
startup, while a separately managed ARQ worker can execute an exact PostgreSQL
task by ID. Business endpoints do not publish work yet. PostgreSQL remains the
source of truth; a transactional outbox is still required before production.

## Code map

```text
backend/src/aijaa/
├── api/
│   ├── app.py                 FastAPI application, health, metrics, frontend mount
│   ├── routers/               CV, seeker, discovery, approval, application, task APIs
├── application/
│   ├── analyzer.py            ATS detection and application-plan creation
│   ├── answers.py             Field classification and safe answer routing
│   ├── browser.py             HTTP and Playwright page drivers
│   ├── executor.py            Fill, evidence, human stop, pre-submit gate
│   ├── service.py             Application workflow orchestration
│   └── validator.py           Confirmation and ambiguous-submit handling
├── core/
│   ├── config.py              Environment configuration
│   ├── db.py                  SQLAlchemy lifecycle and Alembic-head enforcement
│   ├── models.py              Domain models
│   ├── repo.py                Persistence, status transitions, audits, tasks
│   ├── status.py              Application state machine
│   └── tables.py              Cross-dialect SQLAlchemy tables
├── discovery/                 Sources, normalization, dedupe, freshness
├── intake/                    Local parser, intake engine, completeness rubric
├── llm/                       Provider protocols, fakes, OpenAI, Anthropic
├── matching/                  Retrieval, filtering, reranking
├── observability/             Structured logs, metrics, usage, webhooks
├── orchestration/             Reference DB queue, runner, governance controls
├── resume/                    Fact guard, tailoring, IR, DOCX/TXT rendering
└── testkit/                   Local mock ATS and test fixtures

backend/tests/                 Unit, integration, E2E-style, eval, regression tests
backend/fixtures/              Local job postings and application forms
backend/scripts/               Demo and configuration checks
frontend/                      HTML/CSS/JavaScript operator console
database/                      Alembic configuration and versioned migrations
infrastructure/compose.yaml    Local PostgreSQL 16 and Redis 7 services
uv.lock                        Reproducible direct and transitive dependencies
```

### Code-level request path

For a typical local application preparation:

```text
frontend/app.js
  -> api/routers/applications.py
  -> application/service.py
  -> application/analyzer.py
  -> application/executor.py
  -> application/browser.py
  -> core/repo.py
  -> PostgreSQL or SQLite + local_artifacts
```

Status changes must go through `repo.transition_application()`, which validates
the state machine and records both timeline and audit entries.

## Quick start

Requirements:

- Python 3.13 (pinned by `.python-version`)
- [uv](https://docs.astral.sh/uv/) for locked dependency installation
- Docker with Compose for the recommended PostgreSQL/Redis stack
- Node.js only for the JavaScript syntax check
- `just` is optional

### Install

```bash
cd /path/to/AIJAA/aijaa
uv sync --locked --extra dev
```

`uv.lock` pins every direct and transitive dependency. A clean Python 3.13
environment built only from this lock passes the complete test suite.

Pip remains a compatibility option for existing local environments:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### Start PostgreSQL and Redis

```bash
docker compose -f infrastructure/compose.yaml up -d --wait postgres redis
docker compose -f infrastructure/compose.yaml ps
```

The development-only ports are:

- PostgreSQL: `127.0.0.1:55432`
- Redis: `127.0.0.1:6379`

Redis is healthy but unused while `AIJAA_WORKFLOW_MODE=sync`. PostgreSQL is the
recommended local source of truth. Copy the safe local configuration and apply
all migrations before starting the API:

```bash
cp .env.example .env
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check
```

PostgreSQL startup never calls `create_all()`. FastAPI reads
`alembic_version` and refuses to start when the database revision differs from
the application head. Local non-production SQLite and isolated unit tests retain
controlled `create_all()` compatibility.

### Run the safe local console with PostgreSQL

```bash
AIJAA_POSTED_WITHIN_DAYS=60 \
AIJAA_PRODUCTION_MODE=false \
AIJAA_FAKE_LLM=true \
AIJAA_DRY_RUN=true \
AIJAA_APPLY_DRIVER=http \
AIJAA_WORKFLOW_MODE=sync \
AIJAA_DATABASE_URL='postgresql+asyncpg://aijaa:aijaa-local@127.0.0.1:55432/aijaa' \
AIJAA_ARTIFACTS_DIR=./local_artifacts/postgres \
uv run uvicorn aijaa.api.app:app --port 8011
```

Open:

- Web console: <http://127.0.0.1:8011>
- Swagger API: <http://127.0.0.1:8011/docs>
- Health: <http://127.0.0.1:8011/healthz>
- Metrics: <http://127.0.0.1:8011/metrics>

Expected local health fields:

```json
{
  "status": "ok",
  "llm_mode": "fake",
  "dry_run": true,
  "workflow_mode": "sync",
  "production_mode": false,
  "apply_driver": "http"
}
```

`production_ready=true` while `production_mode=false` only means the local
configuration is internally valid. It is not a production-readiness claim.

### Optional queue foundation

The web console currently runs the business workflow synchronously. Queue mode
is present and tested as an infrastructure foundation: FastAPI verifies Redis
on startup, and an ARQ worker can claim one exact PostgreSQL task by ID. The
existing business endpoints do **not** publish their work to Redis yet, so do
not switch the console to queue mode expecting the buttons to become async.

To verify the foundation locally, use two terminals after starting PostgreSQL
and Redis:

```bash
# Terminal 1: start the API and verify its Redis lifecycle
AIJAA_WORKFLOW_MODE=queue \
AIJAA_DATABASE_URL='postgresql+asyncpg://aijaa:aijaa-local@127.0.0.1:55432/aijaa' \
uv run uvicorn aijaa.api.app:app --port 8012

# Terminal 2: start one ARQ worker
uv run arq aijaa.orchestration.worker.WorkerSettings
```

`GET /v1/tasks/{task_id}` exposes the safe task metadata needed for polling;
it deliberately never returns the task payload. The next orchestration step is
to make selected endpoints create an outbox event and publish it transactionally.

### Run the deterministic demo

```bash
just demo
```

The demo uses local fixtures and fake LLMs. It does not spend provider tokens or
submit external applications.

## Using a real CV locally

A real CV can be used in the local console, subject to these constraints:

1. Keep the server bound to localhost and do not expose port 8010 publicly.
2. Upload the file or paste its text.
3. Review every interpreted field before selecting **Save Editable Profile**.
4. Correct companies, titles, dates, salary, work authorization, and
   dealbreakers when the source layout is ambiguous.
5. Treat generated Hebrew artifacts as layout previews while fake mode is on.
6. Use fixtures or manually vetted job URLs and keep `DRY_RUN=true`.

Local candidate records are stored in the configured PostgreSQL or SQLite
database. Generated resumes and HTML/PNG evidence are stored under
`AIJAA_ARTIFACTS_DIR`. There is no encrypted object storage or automated
retention policy in the local MVP.

## API overview

The service currently exposes business endpoints under `/v1`.

### CV and candidate profile

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/cv/parse` | Extract text from an uploaded CV |
| `POST` | `/v1/cv/interpret` | Create editable profile/preference drafts |
| `POST` | `/v1/seekers` | Create a candidate record |
| `POST` | `/v1/seekers/{id}/intake/turns` | Save a new profile version |
| `GET` | `/v1/seekers/{id}/profile` | Read the latest profile and completeness |
| `POST` | `/v1/seekers/{id}/resume` | Generate an EN or HE master resume |
| `GET` | `/v1/seekers/{id}/resume/latest` | Read the latest master resume |
| `GET` | `/v1/seekers/{id}/usage` | Read candidate-scoped LLM usage |

### Discovery, matching, and decisions

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/discovery/run` | Run configured job sources |
| `POST` | `/v1/jobs/manual` | Add or fetch a manually supplied job URL |
| `POST` | `/v1/seekers/{id}/match/run` | Filter and rank jobs for a candidate |
| `GET` | `/v1/seekers/{id}/matches` | List surfaced matches |
| `POST` | `/v1/matches/{id}/decision` | Approve or reject one match |
| `POST` | `/v1/seekers/{id}/matches/decisions` | Submit batch decisions |
| `GET` | `/v1/matches/{id}/handoff` | Build the operator handoff packet |
| `GET` | `/v1/seekers/{id}/pipeline` | Read application/task/dead-letter counts |
| `GET` | `/v1/usage` | Read global LLM usage |
| `GET` | `/v1/tasks/{task_id}` | Read a queued worker task without exposing its payload |

### Application preparation and confirmation

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/applications/{id}/tailor` | Generate the job-specific resume |
| `POST` | `/v1/applications/{id}/preflight` | Analyze the form without filling it |
| `POST` | `/v1/applications/{id}/run` | Run synchronous preparation |
| `POST` | `/v1/applications/{id}/human-input` | Save human answers and resume preparation |
| `POST` | `/v1/applications/{id}/confirm-submit` | Invoke the final confirmation gate |
| `GET` | `/v1/applications/{id}` | Read the application record |
| `GET` | `/v1/applications/{id}/timeline` | Read merged status, audit, and evidence events |

Operational endpoints:

- `GET /healthz`
- `GET /metrics`
- `GET /docs`
- `GET /openapi.json`

When `AIJAA_PRODUCTION_MODE=false`, a mock ATS is mounted under `/mockboard`
for local tests. It is not mounted in production mode.

## Application states

```text
discovered
  -> matched
  -> approved | failed
  -> tailored
  -> applying
  -> needs_human <-> applying
  -> ready_to_submit
  -> submitted
  -> confirmed | needs_human | failed
```

`needs_human` is a safety state, not a generic failure. CAPTCHA, login, sensitive
questions, unsupported required fields, profile drift, form drift, and ambiguous
post-click outcomes must stop for human review.

## Safety invariants

- `AIJAA_DRY_RUN=true` by default.
- No tailoring or application preparation without explicit match approval.
- Match scores below `AIJAA_MATCH_FLOOR` are withheld.
- Resume and answer generation is checked against candidate facts.
- Salary, legal status, clearance, demographic, and unsupported questions route
  to a human.
- CAPTCHA, login, 2FA, and bot walls are never bypassed.
- An ambiguous post-submit state is never automatically retried.
- Application status changes are validated and audited.
- Local sync mode does not create queue rows that no worker will consume.

These invariants reduce risk; they do not replace authentication, tenant
isolation, idempotent submission attempts, or production infrastructure.

## Configuration

All settings use the `AIJAA_` prefix.

| Setting | Local default | Purpose |
|---|---|---|
| `AIJAA_DATABASE_URL` | SQLite in code; PostgreSQL in `.env.example` | Database connection URL |
| `AIJAA_REDIS_URL` | `redis://127.0.0.1:6379/0` | Future worker delivery queue |
| `AIJAA_ARTIFACTS_DIR` | `./artifacts` | Resume and evidence output directory |
| `AIJAA_PRODUCTION_MODE` | `false` | Disable local fixtures and mock controls when true |
| `AIJAA_WORKFLOW_MODE` | `sync` | Sync console execution or opt-in reference queue |
| `AIJAA_FAKE_LLM` | `true` | Use deterministic provider fakes |
| `AIJAA_LLM_PROVIDER` | `fake` | `fake`, `openai`, or `anthropic` |
| `AIJAA_DRY_RUN` | `true` | Suppress external submit clicks |
| `AIJAA_APPLY_DRIVER` | `http` | `http` for local forms; `playwright` for browser flows |
| `AIJAA_MATCH_FLOOR` | `70` | Minimum surfaced match score |
| `AIJAA_POSTED_WITHIN_DAYS` | `21` | Posting freshness window |
| `AIJAA_APPLICATIONS_PER_DAY` | `10` | Per-candidate daily cap |
| `AIJAA_BROWSER_POOL_MAX` | `3` | Browser concurrency ceiling |
| `AIJAA_DOMAIN_APPLICATION_INTERVAL_SECONDS` | `120` | Per-domain application pacing |
| `AIJAA_GREENHOUSE_ORGS` | empty | Comma-separated public board IDs |
| `AIJAA_LEVER_ORGS` | empty | Comma-separated public board IDs |

`.env.example` is a configuration reference, not a statement that the current
repository is safe to deploy. Do not place real secrets in Git.

## Tests and quality gates

Run the complete local gate:

```bash
uv run --locked --extra dev pytest -q
uv run --locked --extra dev ruff check .
node --check frontend/app.js
uv lock --check
git diff --check
```

Or:

```bash
just ci
```

The suite covers:

- CV parsing and English/Hebrew interpretation regressions.
- Profile completeness and required preferences.
- Resume truthfulness and artifact generation.
- Freshness, deduplication, dealbreakers, and match score floors.
- Approval immutability and downstream authorization gates.
- Human-question pause and resume.
- CAPTCHA stops and zero bypass attempts.
- Dry-run suppression and ambiguous-submit behavior.
- Task idempotency, governance, dead letters, and local sync behavior.
- SQLite-local and PostgreSQL-migration startup policy.
- API timeline, metrics, usage, and production-mode configuration checks.

`QA_CHECKPOINT.md` records the verified local checkpoints and manual acceptance
history.

## Observability

- Structured logs are emitted through `structlog` with configured redaction.
- Status transitions, decisions, human input, evidence, and submit events are
  retained in the audit/timeline model.
- `GET /metrics` exposes Prometheus text metrics.
- Candidate and global usage endpoints aggregate provider calls and tokens.

Metrics, usage, timelines, artifacts, and readiness are not protected yet and
must not remain public in production.

## Production gaps

Before processing live candidate data or enabling external submission, the
following are required:

1. Cognito authentication with mandatory MFA and server-side JWT validation.
2. Organization ownership and tenant-scoped repositories on every `/v1` route.
3. Production RDS, tenant foreign keys, timestamps, backup/restore, and schema
   hardening beyond the verified local PostgreSQL/Alembic foundation.
4. Redis/arq publication from business endpoints plus a transactional PostgreSQL outbox.
5. Immutable submission authorizations, review versions, idempotency keys, and
   separate submission-attempt records.
6. S3/KMS private artifacts, signed downloads, lifecycle rules, and deletion
   workflows.
7. Upload size/MIME/signature validation, quarantine, and malware scanning.
8. HTTPS-only manual URLs with redirect validation, DNS/IP protections, and
   response limits.
9. Playwright/Chromium startup enforcement with no HTTP-driver fallback.
10. Certified Greenhouse and Lever browser flows and manual handoff for unknown
    portals.
11. PostgreSQL/Redis/browser integration tests, measurable quality evals, CI/CD,
    infrastructure as code, monitoring, backups, and operational runbooks.

The intended production architecture is AWS `eu-central-1` with ECS/Fargate,
ALB/WAF, Cognito, RDS PostgreSQL, ElastiCache Redis, encrypted S3, CloudWatch,
and separate API, worker, browser-worker, and scheduler services.

## Development rules

- Keep `DRY_RUN=true` during development and staging validation.
- Treat the candidate profile as the source of truth for every generated claim.
- Preserve human approval and pre-submit confirmation as separate gates.
- Add regression tests before fixing parsing, matching, or submission bugs.
- Do not scrape access-controlled boards or bypass platform protections.
- Do not enable queue mode without a running worker.
- Do not commit local databases, candidate documents, artifacts, or secrets.

## Related documentation

- `QA_CHECKPOINT.md` — verified checkpoints and manual QA history.
- `AIJAA_Prompt_Chain.md` — original product and architecture prompt chain.
- `CLAUDE.md` — repository conventions and implementation history.
