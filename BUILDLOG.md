# Build Log

## 2026-10-14 — Phase 1 design gate

AI assistance was used to extract and organize the supplied FlyRank capstone brief into `docs/design.md`, including proposed implementation decisions and a test plan. No application code, migrations, Docker configuration, or endpoints were created.

Human review is pending for the design decisions, especially the project-defined Pro quotas, pricing configuration approach, billing-month boundary, authentication model, and alerting adapter. Human verification against the official brief and all future evidence/test outputs is pending.

## 2026-10-14 — Phase 2 foundation

The initial Phase 2 foundation was created: the layered application skeleton, a liveness `GET /health` endpoint, Docker Compose services for the app and PostgreSQL, and a `.dockerignore` were added. Ruff checks passed, pytest passed with 1 test, Python compilation passed, and `git diff --check` passed. The hardened Compose configuration passed `docker compose config --quiet`. The containers started successfully, PostgreSQL became healthy, and `GET http://localhost:8000/health` returned HTTP 200 with `{"status":"ok"}`. The app container connected successfully to PostgreSQL and `SELECT 1` returned `1`. The existing PostgreSQL role password was updated to match the password in the local `.env` file without deleting the database volume.

No migrations, business logic, authentication, billing, Stripe webhooks, or background jobs were implemented. No acceptance probes have passed or been claimed.

## 2026-10-14 — Design revision

AI assistance revised the design against the supplied brief and review instructions. It made token inclusion/validation, UTC periods, tenant API-key identity, PostgreSQL duplicate-conflict handling, subscription event ordering, an alert-outbox job, and example project-defined integer pricing explicit. No implementation files were created or run. Human review and verification remain pending; no tests or acceptance probes have passed or been claimed.

## 2026-10-16 — Phase 3.1 database foundation

SQLAlchemy 2.x declarative models were added for tenants, API key hashes, plans, subscriptions, usage events, Stripe events, tenant-month quota state, and alert outbox records. A shared `Base` is imported through `app.models` for Alembic metadata. Alembic was initialized with the existing settings-backed PostgreSQL URL, and the reviewed initial migration creates the tables, foreign keys, indexes, timestamp columns, token and cost checks, tenant-scoped idempotency uniqueness, Stripe event deduplication, quota-state uniqueness, and alert identity uniqueness.

The focused metadata tests and full pytest suite passed with 3 tests. Ruff checks, Python compilation for `app` and `migrations`, and `git diff --check` passed. `alembic upgrade head --sql` generated the initial SQL offline successfully; the migration was not applied, no database volume was deleted, and no destructive database command was run. API business logic, quota enforcement, authentication, billing, Stripe processing, and background jobs remain unimplemented; no acceptance probes have passed or been claimed. The foundation was later reverified during the schema review below.

## 2026-10-16 — Phase 3.1 schema review corrections

The initial schema was reviewed and corrected without changing its architecture or table scope. Usage events now require at least one API call; plan API-call and AI-token limits must be nonnegative; and alert attempts must be nonnegative while alert thresholds must be between 1 and 100. The corresponding named model constraints, initial-migration constraints, database defaults, and database-free metadata tests were updated consistently.

The requested Ruff check, full pytest suite, Python compilation check, `git diff --check`, and offline `alembic upgrade head --sql` generation all passed; pytest passed with 7 tests, including server-default metadata assertions. The migration was not applied, PostgreSQL was not connected to, no volume was deleted, and no acceptance probes have passed or been claimed.

## 2026-10-21 — Stripe Stage B webhook synchronization

Verified Stripe webhook handling was added for Checkout completion and subscription updates/deletions. Raw-body signatures are checked with the official Stripe SDK before processing; event IDs are deduplicated transactionally; tenant metadata and stored Stripe identifiers are cross-checked; subscription updates lock the tenant row; and stale events reconcile against authoritative Stripe subscription state without regressing newer local metadata. Active and trialing subscriptions remain billable, while inactive and unpaid states return HTTP 402 from generation. No migration was required because the existing Stripe event and subscription schema contained the required fields.

Focused and full pytest runs passed for available tests; PostgreSQL integration tests were skipped because `TEST_DATABASE_URL` was not configured. Ruff format/check and offline Alembic SQL generation passed using temporary non-secret Stripe setting values. No database was modified, and alerting/background jobs remain unimplemented.

## 2026-10-21 — Usage threshold alert outbox and worker

An 80% monthly quota threshold outbox was added for API calls and AI tokens. Alert creation occurs in the same transaction as usage-event and quota-state updates, with a database uniqueness key preventing repeated alerts per tenant, month, usage type, and threshold. A PostgreSQL-safe worker claims pending alerts with `FOR UPDATE SKIP LOCKED`, delivers through an injectable adapter using the alert ID as an idempotency key, records delivery status, retries transient failures up to three attempts with bounded backoff, and marks permanent failures terminal. Stale processing claims can be reclaimed using the existing `updated_at` field. No migration was required because the existing alert table contained the necessary identity, retry, availability, error, and delivery fields.

Unit tests passed; the full suite passed with PostgreSQL integration tests skipped because `TEST_DATABASE_URL` was not configured. Ruff format/check passed. No database or volume was reset, and final submission work was not started.

## 2026-10-21 — PostgreSQL alert-worker verification

The local Docker PostgreSQL instance already contained the `flyrank_test`
database. A shell-only `TEST_DATABASE_URL` was constructed from the existing
local environment for test execution without modifying `.env` or exposing
credentials. The focused alert integration suite passed with 4 tests, including
the strict exactly-one-worker claim assertion. The full PostgreSQL-backed suite
reported 92 passed and one pre-existing Starlette/httpx deprecation warning.

The worker test diagnosis found a SQLAlchemy transaction-lifecycle issue in the
diagnostic test session: a read implicitly opened a transaction before the
worker claim helper called `Session.begin()`. Rolling back the read transaction
before `_claim_alert()` fixed the test without changing `FOR UPDATE SKIP LOCKED`.
The generation concurrency test cleanup was also updated to delete its
transactionally-created alert outbox rows before deleting the tenant.

## 2026-10-21 — Submission-readiness documentation

README, acceptance evidence, and this build-log update document the implemented
metering, quota, usage, Stripe, migration, and alert behavior. Historical
verification results are explicitly labeled and are not represented as rerun
during this documentation milestone.

No authoritative `capstone.yaml` schema or example was found in the workspace
or repository history, so that file was not invented. The alert worker has no
standalone scheduler or process entrypoint; its service functions are
documented as not independently runnable. Live Stripe test-mode acceptance
probes, official evidence capture, and any required capstone metadata remain
to be completed.

## 2026-10-26 — Official brief reconciliation and submission pack

The original official FlyRank brief became available in the working
conversation. Its Sections 6, 8, 10, 11, and 12 were compared with the
repository. The brief confirms the required submission files, five behavioral
probes, and the shared requirement for at least one background job with
retries and failure alerting. It does not require a continuously running
scheduler.

The submission manifest was added as `capstone.yaml` using only the explicitly
specified fields: `run`, `seed`, optional `test`, `base_url`, and probe
endpoints. The README and evidence checklist were updated to use the official
requirements rather than treating `docs/design.md` as the sole source.

The alert worker previously had service functions but no runnable invocation
or terminal failure signal. A bounded `app.jobs.alert_worker` CLI and a local
non-sensitive logging notification adapter were added. Terminal delivery
failures remain persisted as `failed` and now emit a structured failure log;
payloads and credentials are not logged. Unit tests cover the CLI-facing
adapter behavior and failure alert.

Live Stripe CLI acceptance probes remain unverified because no live test-mode
credentials and webhook session were used. No application database was reset,
and no secrets were added.

Verification for this milestone: the alert worker unit suite passed with
5 tests; the full PostgreSQL-backed suite passed with 94 tests and one
pre-existing Starlette/httpx warning; Alembic reported no new upgrade
operations at `20261016_0001 (head)`; Docker Compose configuration, Ruff, and
`git diff --check` passed. Live Stripe CLI probes were not run.

## 2026-10-26 — Acceptance evidence verification

The focused acceptance coverage ran against the existing isolated PostgreSQL
database: 12 tests passed with one pre-existing Starlette/httpx warning. The
focused alert-worker suite passed with 5 tests. The full PostgreSQL-backed
suite passed with 94 tests and one warning. Ruff formatting/checks,
`git diff --check`, Docker Compose configuration, and the application image
build passed. Alembic reported no new upgrade operations and revision
`20261016_0001 (head)`.

The submission-pack inspection found that the original Docker image omitted
`migrations/` and `scripts/`, which made the manifest seed command unusable
inside the container. The Dockerfile now copies both directories, and the
manifest runs Compose detached so its seed command can execute afterward.

Live Stripe evidence remains unavailable: the local `.env` does not define the
three Checkout settings and the Stripe CLI is not installed. No Stripe live or
test-mode Checkout was attempted, and no secret values were displayed.

## 2026-10-26 — Live Stripe Checkout and webhook replay verification

Live Stripe test-mode verification was completed using a locally configured Stripe test account and Stripe CLI webhook forwarding.

A tenant completed the Pro Checkout flow. The subsequent `GET /usage` response reported `plan_name: Pro`, `subscription_status: active`, an API-call limit of 100,000 per month, and an AI-token limit of 10,000,000 per month.

The existing `checkout.session.completed` event was replayed using Stripe CLI. The local webhook endpoint acknowledged both deliveries with HTTP 200. A read-only query against the PostgreSQL `stripe_events` table found exactly one row for the event ID, with `processed_at` populated. The table schema also confirmed a unique constraint on `stripe_event_id`.

The application was rebuilt and recreated with Docker Compose after local Stripe configuration changes, and `GET /health` returned `{"status":"ok"}`. Repository hygiene checks confirmed that `.env` is ignored by Git and is not tracked. `git diff --check` passed. The repository-wide secret scan found no Stripe credentials in tracked files. Its remaining matches were mock tenant API-key values used by the tenant-bootstrap unit tests.

These observations verify the live test-mode Checkout upgrade and duplicate event-record prevention for the tested replay. They do not independently verify a live forged-signature request or every possible downstream side effect. Webhook-secret rotation remains to be confirmed.
