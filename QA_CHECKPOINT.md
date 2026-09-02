# AIJAA — Current Checkpoint

**Date:** 2026-09-02 · **Status:** local MVP plus PostgreSQL/Redis worker foundation.

Current verification target:

```bash
.venv/bin/ruff check backend/src backend/tests database/migrations
node --check frontend/app.js
.venv/bin/python -m pytest -q
```

Expected result: 92 tests pass. The local parser extracts multiple jobs,
month-level dates, education, salary preferences, and Hebrew section headings.
The UI restores the active seeker/application, resolves `needs_human` questions
without curl, prevents stale static assets, blocks placeholder candidate data,
invalidates reviews after profile changes, rebuilds resume artifacts by profile
version, and keeps dry-run submission non-destructive. Local workflows now run in
explicit `sync` mode and do not create orphaned task rows. PostgreSQL/Alembic,
Redis lifecycle checks, an ARQ worker, exact task claiming, and a task-status API
are present; business endpoints do not publish queue jobs yet. Authentication/tenant isolation,
durable submission attempts, hardened storage/network inputs, CI/CD, and AWS
infrastructure remain production blockers.

The two checkpoints below are retained as historical build records; their test
counts and "next phase" wording describe the repository at those dates.

---

# AIJAA — QA Checkpoint #1

**Date:** 2026-07-16 · **Status:** MVP slice + full application engine built and verified (36 tests green, zero API usage). This is the pre-determined checkpoint promised before finishing development. Please run the checks below and confirm before I proceed to the final phase (orchestration-lite, full audit/metrics surface, and the mock-board E2E + eval gates).

---

## What exists now (and maps to the PRD)

| PRD element | Built | Where |
|---|---|---|
| Sophisticated intake form | Adaptive interview engine, code-scored completeness rubric (85 threshold + hard fields) | `intake/` |
| Resume, EN **and/or** Hebrew | Fact-traceable IR → ATS-safe docx (RTL for Hebrew) + txt; fabrication guard | `resume/` |
| Curated jobs, up-to-date, **7/10+** | Connectors → normalize/dedupe/freshness → RAG rerank; **< 70 withheld, never shown** | `discovery/`, `matching/` |
| Human approval before applying | Per-job attributable decision; downstream gate; no auto-approve | `api/routers/approvals.py`, `application/gate.py` |
| Recruiter-first MVP (manual apply) | Handoff packet endpoint (job + rationale + resume artifacts) | `GET /v1/matches/{id}/handoff` |
| "Analyze how to apply" then apply | Fingerprint + form-schema + confidence-scored plan **before** touching anything | `application/analyzer.py` |
| Apply until validated | Executor fills → **stops at pre-submit gate** → validate confirmation/receipt | `application/executor.py`, `validator.py` |
| Tailor before applying (after approval) | Fact-safe tailor + before/after ATS score, runs post-approval | `resume/tailor.py` |
| Self-compatible to any application | Generic HTML form parser + per-platform fingerprint; account-required ATS → human | `application/forms.py`, `fingerprint.py` |
| Honesty over confidence | CAPTCHA/login/bot-wall → `needs_human` (never bypassed); ambiguous submit → `needs_human` (never double-submit) | `forms.detect_interrupts`, `validator.retry_decision` |
| Living document (90-day decay) | Staleness flag surfaced on profile + matching warnings | `repo.profile_is_stale` |

**Not yet built (next phase):** in-process orchestration/queue with per-domain rate limits, the full metrics/audit-timeline API surface, the mock-board E2E test, and the truthfulness/relevance eval gates. Your sign-off here gates that work.

---

## Setup (one time)

```bash
cd /Users/amitbakshi/AIJAA/aijaa
python3 -m venv .venv            # needs Python 3.12+ (built/tested on 3.13)
.venv/bin/pip install -e ".[dev]"
```

## QA-1 — Automated suite (fastest signal)

```bash
.venv/bin/python -m pytest -q      # expect: 36 passed
.venv/bin/ruff check backend/src backend/tests database/migrations  # expect: clean
```

The suite is the acceptance harness. Notable guarantees it encodes:
- `test_core.py` — state machine rejects skipping the approval gate; no double-apply; every transition audited.
- `test_intake.py` — completeness rubric; hard fields (salary/location/work-auth) gate completion; earlier answers never dropped.
- `test_resume.py` — fabrication guard catches invented metrics/skills/unknown facts; **Hebrew docx renders RTL**; ATS score is deterministic and drops when content is stripped.
- `test_discovery_matching.py` — stale posting dropped, URL-dup collapsed, **nurse job withheld below floor**, **gambling job dealbreaker-filtered**; decisions attributable/immutable/idempotent; handoff packet only for approved; **gate blocks without approval**.
- `test_application.py` — greenhouse form fills & **stops at `ready_to_submit`** (0 submits under DRY_RUN); **CAPTCHA → `needs_human`, 0 submit attempts**; comp question → pause → human input → resume; **live submit confirms with exactly 1 submit**; **ambiguous submit → `needs_human`, never retried**.

## QA-2 — Watch the whole pipeline (recommended)

```bash
.venv/bin/python backend/scripts/demo_pipeline.py    # or: just demo
```

Prints all 7 stages for a fixture seeker "Dana Levi". Confirm you see:
- Intake completeness reaching 100 / complete.
- Two resumes written (`master_en_*.docx`, `master_he_*.docx` under `./demo_artifacts/<seeker>/`) — **open the `_he_` docx and verify it reads right-to-left**.
- Discovery: `fetched 6, stale_dropped 1, created 4` (dedupe + freshness working).
- Matching: DataStream (91) and Cloudify (77) surfaced; **no nurse job, no gambling job**.
- Application engine ending at `status=ready_to_submit`, `platform=greenhouse`, `confidence=high`, evidence `[review_packet, screenshot]`.
- Confirm-submit: `status=applying, submit_suppressed=True` (DRY_RUN protected the world).

## QA-3 — Poke the live API (optional)

```bash
just run     # uvicorn on http://127.0.0.1:8000  — see /docs for the full surface
```

Key endpoints to try in `/docs`: `POST /v1/seekers` → `POST /v1/seekers/{id}/intake/turns` → `POST /v1/seekers/{id}/resume` → `POST /v1/discovery/run` (body `{"fixtures_dir": "backend/fixtures/postings"}`) → `POST /v1/seekers/{id}/match/run` → `GET /v1/seekers/{id}/matches?status=pending` → `POST /v1/matches/{id}/decision` → `GET /v1/matches/{id}/handoff`. `GET /healthz` shows `llm_mode` and `dry_run`.

---

## What I need from you at this checkpoint

1. **Confirm the suite + demo pass on your machine** (Python 3.12+; if `just` isn't installed, use the `.venv/bin` commands directly).
2. **Sanity-check the two judgment surfaces** that will use Claude in production but run on deterministic fakes here — the **match rationale/scoring** and the **resume/answer wording**. Everything is structured so flipping `AIJAA_FAKE_LLM=false` (with `ANTHROPIC_API_KEY` set) swaps in Claude with no other change; say the word if you'd like me to wire and smoke-test a real-Claude run (this will spend tokens).
3. **Confirm the guardrail posture matches your intent** — especially: withhold-below-70 (not "show as low confidence"), pre-submit human validation on every application, and hard-stop (no bypass) at CAPTCHAs/logins. These are enforced in code, not config.
4. **Flag any scope changes** before I build the final phase.

## Questions worth your call (defaults in parens)

- Real job boards for discovery: which orgs/sources should the production connectors target? (Greenhouse/Lever public boards are wired; LinkedIn/Indeed are deliberately **not** scraped per the PRD's litigation-risk note.)
- Submission channel for `needs_human` / handoff notifications: webhook to your system is built (`AIJAA_OPERATOR_WEBHOOK_URL`); want email drafts too?
- When you're ready to leave DRY_RUN, we flip it per-environment only after the E2E + eval gates in the final phase pass (documented policy, not a code default).

Reply with go/no-go (and any answers above) and I'll complete orchestration, the full audit/metrics surface, and the mock-board E2E with eval gates.

---

# AIJAA — QA Checkpoint #2

**Date:** 2026-07-16 · **Status:** local orchestration, governance, observability
surfaces, mock-board harness, eval gates, and operator runbook implemented.

## What changed after QA-1

- DB-backed in-process task queue with idempotency keys, task statuses, and
  dead-letter records.
- Governance defaults for per-seeker browser concurrency, global browser pool,
  daily application caps, and per-domain application pacing.
- Approval and human-input events enqueue local pipeline tasks while direct QA
  endpoints remain available.
- `GET /v1/seekers/{id}/pipeline`, `GET /metrics`,
  `GET /v1/seekers/{id}/usage?window=30d`, `GET /v1/usage?window=30d`, and a
  merged chronological application timeline.
- Expanded mock-board testkit with a Greenhouse-shaped feed, single-page form,
  multi-step/human-question flow, CAPTCHA wall, and flaky submission mode.
- CI-mode eval tests for matcher relevance, tailoring truthfulness, and screening
  answer traps.
- `README.md` operator runbook and DRY_RUN flip policy.

## QA-2 Commands

```bash
cd /Users/amitbakshi/AIJAA/aijaa
just ci
just demo
```

Expected: lint clean, import/type smoke clean, all tests pass, demo completes with
zero API usage. `just demo` removes `demo.db` first, so discovery counts should show
the fresh-run created/updated split documented in QA-1.
