# Acceptance Evidence

This document records evidence against the official FlyRank capstone brief, particularly Section 6 requirements and Section 12 evaluation probes. Automated tests, historical verification, and live Stripe test-mode observations are distinguished explicitly. No result is marked as observed unless it was reported as run.

## Acceptance criteria

| Criterion | Test or command | Observed result | Evidence still missing |
|---|---|---|---|
| Idempotent generation | `tests/integration/test_generation_service_integration.py`; `tests/integration/test_generate_endpoint.py` | PASS: same tenant, idempotency key, and payload return the saved response and one usage event; changed payload returns 409 | A standalone HTTP transcript is not captured |
| Quota boundary | Generation integration and concurrency tests | PASS (automated/historical): exact boundary succeeds, next request returns 429, and concurrent requests cannot exceed quota | A standalone HTTP transcript is not captured |
| Pricing | `tests/unit/test_pricing.py` | PASS: cached input is cheaper, integer rounding is applied once, and reasoning tokens are not double-counted | A standalone pricing and usage transcript is not captured |
| Usage and cost reporting | `tests/integration/test_usage_endpoint.py` | PASS: current-month usage, plan limits, subscription status, integer costs, and tenant isolation are covered | A standalone usage transcript beyond the live Stripe upgrade is not captured |
| Stripe Checkout session creation | `tests/integration/test_stripe_checkout.py` with fake adapter | PASS: mocked adapter tests cover customer reuse and ensure Checkout creation alone does not activate Pro | None for mocked coverage; live evidence is recorded below |
| Live Stripe Checkout: Free to Pro | `POST /stripe/checkout`, Stripe test-mode Checkout, Stripe CLI webhook forwarding, then `GET /usage` | **PASS — observed live in Stripe test mode:** Checkout session was created, test checkout completed, and `GET /usage` returned `plan_name: Pro`, `subscription_status: active`, `api_call_limit: 100000`, and `ai_token_limit: 10000000` | A sanitized Stripe CLI event transcript and saved before/after usage responses are not captured in this document |
| Verified Stripe upgrade | `tests/integration/test_stripe_webhooks.py::test_verified_upgrade_updates_usage_limits`; live Checkout flow described above | PASS: automated verified-upgrade test passed; live test-mode flow also produced active Pro status and expected limits through `GET /usage` | Standalone sanitized event transcript is not captured |
| Webhook signature security | Invalid-signature and malformed-payload tests in `tests/integration/test_stripe_webhooks.py` | PASS (automated): invalid or malformed requests return 400 without database mutation | A captured live forged-signature HTTP probe is not recorded |
| Webhook replay | `tests/integration/test_stripe_webhooks.py::test_duplicate_event_is_safe_noop`; live Stripe test-mode replay | **PASS:** Automated duplicate-event test passed. In live test mode, the same `checkout.session.completed` event was forwarded twice; both deliveries received HTTP 200, and the database contained exactly one matching `stripe_events` row. | Live forged-signature HTTP probe is not captured; duplicate side-effect verification beyond event-record deduplication is not independently demonstrated |

### Stripe webhook replay and deduplication — PASS
Verified in Stripe test mode on 26 October 2026.

- Replayed the existing `checkout.session.completed` event using Stripe CLI.
- Event ID: `evt_1UUtWH2ZwDNYxzgINifZG7Lx`.
- Stripe CLI forwarded the same event twice to `POST /webhooks/stripe`; both deliveries received HTTP 200.
- Queried the PostgreSQL `stripe_events` table using the event ID. Exactly one row existed, with `event_type = checkout.session.completed` and `processed_at` populated.
- Inspected the table schema and confirmed the unique constraint `uq_stripe_events_event_id` on `stripe_event_id`.
- Rechecked `GET /usage`; the tenant remained on the active Pro plan with limits of 100,000 API calls and 10,000,000 AI tokens per month.

**Result:** The repeated event delivery was acknowledged successfully and did not create a duplicate `stripe_events` record. This verifies event-record deduplication for the tested replay.

| Webhook ordering | `test_stale_event_reconciles_authoritative_state` | PASS (automated): stale event does not regress subscription state and authoritative retrieval is used | Live reconciliation evidence is not captured |
| Inactive subscription billing | `test_deleted_subscription_is_not_billable` | PASS (automated): deleted subscription makes generation return 402 | A standalone API transcript is not captured |
| Alert threshold creation | `tests/integration/test_alerts.py`; `tests/unit/test_alert_thresholds.py` | PASS (historical): API-call and AI-token 80% crossings enqueue once; rollback and duplicate prevention are covered | Rerun output for this milestone is not captured |
| Alert delivery and retry | `.venv/bin/python -m pytest tests/unit/test_alert_worker.py -q` | PASS: 5 tests passed, covering successful delivery, transient retry, terminal failure, stable notification IDs, and non-sensitive failure logging | Production notification adapter delivery evidence is not captured |
| Concurrent alert claiming | `tests/integration/test_alerts.py::test_two_workers_claim_one_alert` | PASS (historical): four alert integration tests passed, including exactly-one worker claim | Rerun output for this milestone is not captured |
| Tenant/API-key isolation | `tests/integration/test_api_key_auth.py`, usage and endpoint tests | PASS (historical): invalid/revoked keys are rejected and tenant data is isolated | A standalone security probe transcript is not captured |
| PostgreSQL migrations | `.venv/bin/alembic current`; `.venv/bin/alembic check`; `.venv/bin/alembic upgrade head` against isolated `flyrank_test` | PASS: current revision `20261016_0001 (head)`; no new upgrade operations detected; upgrade completed successfully | No migration gap identified; application acceptance evidence is separate |
| Full PostgreSQL suite | `.venv/bin/python -m pytest -q -rs` with `TEST_DATABASE_URL` targeting `flyrank_test` | Actual run: `94 passed, 1 warning` | None for this recorded test run |
| Formatting and lint | `.venv/bin/ruff format --check app tests`; `.venv/bin/ruff check app tests`; `git diff --check` | PASS: formatting, lint, and diff checks all passed | None for these recorded commands |
| Runnable alert process | `.venv/bin/python -m app.jobs.alert_worker --help` | PASS: CLI help runs and bounded execution is available through `--max-alerts`; retry and terminal-failure logging behavior are covered by worker tests | A continuously running scheduler is intentionally not included; the brief does not require one |

## Official Section 12 evaluation probes

### Probe 1 — Same billable request twice

**Automated test:** `tests/integration/test_generate_endpoint.py::test_generate_endpoint_is_idempotent_over_http`

**Observed result:** The focused acceptance test command passed as part of a run reporting `12 passed, 1 warning`. The test asserts that repeating a request with the same idempotency key returns matching responses and creates exactly one usage event.

**Status:** PASS — automated PostgreSQL evidence. A standalone curl transcript is not captured.

### Probe 2 — Exact quota boundary and next request

**Automated test:** `tests/integration/test_generate_endpoint.py::test_generate_endpoint_rejects_request_over_quota`, together with generation integration and concurrency tests.

**Observed result:** The focused acceptance command reported `12 passed, 1 warning`. Automated coverage verifies that the exact documented quota boundary is accepted and the subsequent over-limit request returns 429 with quota details.

**Status:** PASS — automated PostgreSQL evidence. A standalone curl transcript is not captured.

### Probe 3 — Stripe Checkout upgrades Free to Pro

**Live test-mode procedure observed:**

1. Created a Checkout session using `POST /stripe/checkout`.
2. Completed Checkout in Stripe test mode.
3. Forwarded Stripe webhook events to the local API using Stripe CLI.
4. Queried `GET /usage` using the tenant's API key.

**Verification command:**

```bash
curl -sS http://localhost:8000/usage \
  -H "X-API-Key: ${FLYRANK_API_KEY}"
```

**Observed response:**

```json
{
  "billing_month": "2026-10-01",
  "plan_name": "Pro",
  "subscription_status": "active",
  "api_calls_used": 0,
  "api_call_limit": 100000,
  "ai_tokens_used": 0,
  "ai_token_limit": 10000000,
  "cost_micro_units": 0
}
```

**Status:** PASS — live Stripe test-mode Checkout and upgrade observed. The response confirms active Pro status and the expected Pro limits.

**Scope limitation:** The before-Checkout response and a sanitized Stripe CLI event transcript were not saved here. This probe does not by itself prove real-event replay idempotency or live forged-signature rejection.

### Probe 4 — Forged webhook and duplicate replay

**Automated tests:**
- `tests/integration/test_stripe_webhooks.py::test_invalid_signature_does_not_mutate_database`
- `tests/integration/test_stripe_webhooks.py::test_duplicate_event_is_safe_noop`

**Observed automated result:** These tests were included in the focused acceptance run reporting `12 passed, 1 warning`. Invalid signatures are rejected without database mutation, and duplicate events are treated as safe no-ops.

**Status:** PASS — automated PostgreSQL evidence.

**Live replay status:** PASS — automated tests; no live forged-signature probe captured. Duplicate replay: PASS — automated test plus live Stripe replay, with two HTTP 200 deliveries and exactly one stored event row.

### Probe 5 — Pinned pricing and usage totals

**Automated test:** `tests/unit/test_pricing.py`, together with `tests/integration/test_usage_endpoint.py`.

**Observed result:** The focused acceptance command reported `12 passed, 1 warning`. Automated tests cover cached-input pricing, reasoning-token inclusion without double counting, and integer rounding. Usage endpoint tests cover reporting of usage, limits, and integer costs.

**Status:** PASS — automated pricing and reporting evidence. A standalone live generation/pricing HTTP transcript is not captured.

## Background job and shared requirements

| Requirement | Evidence | Status |
|---|---|---|
| Layered architecture | Separation across `app/api/`, `app/services/`, `app/models/`, and `app/integrations/` | PASS — implementation and tests |
| Boundary validation | Generation and Stripe endpoint tests for invalid input, missing keys, malformed payloads, and invalid signatures | PASS — automated |
| At least one background job with retries and failure alert | `app.jobs.alert_worker`, five worker unit tests, terminal failure persistence and non-sensitive failure logging | PASS — implementation and automated tests |
| Real persistence, migrations, and tenant isolation | Alembic migration plus PostgreSQL integration suite and tenant-isolation tests | PASS — automated |
| Idempotency | Generation retry tests and Stripe duplicate-event tests | PASS — automated |
| Secrets hygiene | `.env` is ignored and untracked; `.env.example` uses placeholders; tracked-file scan found only mock tenant API-key values in tests | PASS — targeted repository hygiene checks completed |
| Cost tracking and budget guard | Integer pricing, usage rollup, and quota enforcement tests | PASS — automated |

## Migration verification record

Alembic reads the database URL through application settings. During the earlier isolated PostgreSQL verification, the existing `.env` was not modified. Shell-scoped environment variables targeted the existing `flyrank_test` database and supplied non-secret placeholders for required Checkout settings.

Observed results:

```text
.venv/bin/alembic current
20261016_0001 (head)

.venv/bin/alembic check
No new upgrade operations detected.

.venv/bin/alembic upgrade head
completed successfully with no error output

.venv/bin/alembic current
20261016_0001 (head)
```

This verified migration revision and model metadata against the isolated test database. It did not reset, drop, or delete database data.

For the local Compose demo flow, the database name was separately checked and returned `flyrank`. The following command then completed successfully:

```bash
docker compose exec app sh -c \
  "alembic upgrade head && python -m scripts.seed_plans"
```

Observed output:

```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
Free and Pro plans are present with the expected limits.
```

The Docker image was also corrected to include `alembic.ini`, `migrations/`, and `scripts/`, allowing the migration and seed commands to run inside the container.

## Submission-pack verification

Observed commands and results:

```text
docker compose config --quiet
passed

docker compose build app
completed successfully

.venv/bin/python -m app.jobs.alert_worker --help
passed; bounded --max-alerts option is available

.venv/bin/ruff format --check app tests
passed

.venv/bin/ruff check app tests
passed

git diff --check
passed
```

The full PostgreSQL-backed test suite reported:

```text
94 passed, 1 warning
```

The warning was the existing Starlette/httpx deprecation warning.

## Remaining evidence to capture

1. **Live forged-signature probe:** a separate live HTTP request with an invalid
   Stripe signature has not been recorded; automated tests cover rejection.
2. **Sanitized event evidence (optional):** preserve non-secret Stripe CLI
   output and usage responses if useful. Never record secret keys, webhook
   signing secrets, tenant API keys, or full Checkout URLs.
3. **Downstream replay side effects:** the live replay confirmed one stored
   Stripe event record, but did not independently verify every possible
   downstream side effect.

The live Stripe Checkout upgrade is now verified.

### Live forged-signature probe — PASS

Verified locally on 26 October 2026.

- Sent a POST request to `/webhooks/stripe` with `Stripe-Signature: invalid` and a synthetic event payload.
- Observed HTTP `400 Bad Request`.
- Response body: `{"detail":"Invalid Stripe webhook."}`.

**Result:** The live endpoint rejected the request with an invalid Stripe signature. Database non-mutation for this specific live probe was not independently queried; automated tests cover rejection without database mutation.

## Author

**Venkata Naga Sri Kalyan Somisetty**

Backend AI Engineer Intern – FlyRank AI
