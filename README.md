# FlyRank LLM Usage Metering and Billing Engine

This project is a FastAPI service for metering simulated LLM usage, enforcing
tenant-month quotas, reporting integer costs, and synchronizing subscription
state with Stripe test mode. It uses PostgreSQL, SQLAlchemy, Alembic, and an
injectable Stripe adapter for tests.

## Architecture

```text
Client --API key--> FastAPI routes --validated request--> services
                                      |                  |
                                      v                  v
                                  PostgreSQL       Stripe test mode
                                      ^
                                      |
                         alert outbox <- bounded worker
```

- `app/api/routes/` contains FastAPI endpoints and authentication boundaries.
- `app/services/` contains metering, quota, pricing, Stripe, usage, and alert
  business logic.
- `app/models/` contains SQLAlchemy models.
- `app/integrations/stripe/` contains the Stripe SDK adapter protocol and
  implementation.
- `app/jobs/alert_worker.py` provides a bounded worker CLI for processing alert
  outbox records.
- `migrations/` contains the Alembic schema.
- `scripts/` contains plan seeding and tenant bootstrap commands.

## Prerequisites

- Python 3.13
- Docker and Docker Compose
- A PostgreSQL database
- Stripe test-mode credentials for live Stripe Checkout/webhook testing

Install the project and development dependencies:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Local setup

Copy `.env.example` to `.env` and replace the placeholder values locally.
Never commit `.env` or print its contents. Required settings are:

```text
APP_ENV=development
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/flyrank
STRIPE_SECRET_KEY=your-stripe-test-secret
STRIPE_WEBHOOK_SECRET=your-stripe-webhook-secret
STRIPE_PRO_PRICE_ID=your-stripe-pro-price-id
STRIPE_CHECKOUT_SUCCESS_URL=http://localhost:8000/checkout/success
STRIPE_CHECKOUT_CANCEL_URL=http://localhost:8000/checkout/cancel
```

The supplied Compose file starts PostgreSQL and the FastAPI container. Its
database service uses the `POSTGRES_*` values from `.env`:

```bash
docker compose up --build -d
```

Apply the schema and seed the project-defined plans:

```bash
docker compose exec app sh -c "alembic upgrade head && python -m scripts.seed_plans"
```

For a host-based development run instead, use `.venv/bin/uvicorn app.main:app
--reload` after applying the same migration and seed commands with the host
environment.

The seeded limits are:

| Plan | API calls/month | AI tokens/month |
|---|---:|---:|
| Free | 1,000 | 100,000 |
| Pro | 100,000 | 10,000,000 |

Create a tenant. The command prints the newly generated API key once; store it
securely and do not log or commit it:

```bash
.venv/bin/python -m scripts.bootstrap_tenant --name "Example tenant"
```

The Compose run command publishes the API at `http://localhost:8000`.

## Authentication and endpoints

Tenant endpoints use the `X-API-Key` header. `POST /generate` also requires an
`Idempotency-Key` header. Clients do not provide a `tenant_id`.

Health check:

```bash
curl http://localhost:8000/health
```

Record simulated usage:

```bash
curl -X POST http://localhost:8000/generate \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Idempotency-Key: request-0001" \
  -H "Content-Type: application/json" \
  -d '{
    "input_tokens": 100,
    "cached_input_tokens": 20,
    "output_tokens": 50,
    "reasoning_tokens": 10
  }'
```

Read current UTC-month usage:

```bash
curl http://localhost:8000/usage \
  -H "X-API-Key: YOUR_API_KEY"
```

Start a Pro Checkout session:

```bash
curl -X POST http://localhost:8000/stripe/checkout \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"plan_name":"Pro"}'
```

Stripe sends verified events to:

```text
POST /webhooks/stripe
```

The webhook must include the raw request body and `Stripe-Signature` header.
Supported event types are `checkout.session.completed`,
`customer.subscription.updated`, and `customer.subscription.deleted`.

## Metering, idempotency, and errors

Input and output token counts are validated. Cached input must not exceed input
tokens, and reasoning tokens must not exceed output tokens. Billable tokens are
`input_tokens + output_tokens`; reasoning tokens are not counted twice.

Pricing uses integer micro-units and rounds once per event. The project-defined
rates are:

- fresh input: 1,000,000 micro-units per million tokens
- cached input: 250,000 micro-units per million tokens
- output: 4,000,000 micro-units per million tokens
- API calls: 0 micro-units

Repeating an idempotency key with the same payload returns the saved response
without another usage event. Reusing it with a different payload returns
`409 Conflict`.

An active or trialing subscription may generate usage. Inactive or unpaid
subscriptions return `402 Payment Required`. A request exactly at a quota
boundary succeeds; a request that would exceed a quota returns `429 Too Many
Requests` with quota details and a `Retry-After` header.

## Stripe test mode

Create a Pro Price in Stripe test mode and set its identifier as
`STRIPE_PRO_PRICE_ID`. Configure the Checkout success/cancel URLs and the
webhook signing secret in the environment. Stripe must deliver events to
`/webhooks/stripe`; the application verifies the signature before any database
mutation.

Checkout only creates or reuses a Stripe Customer and creates a Checkout
session. It does not activate Pro locally. A verified webhook is authoritative.
Duplicate event IDs are safe no-ops, and stale events are reconciled against
authoritative Stripe subscription state when needed.

Live Stripe test-mode Checkout and webhook delivery were verified locally. Checkout upgraded the tenant to the active Pro plan with the documented limits. A replayed `checkout.session.completed` event received HTTP 200 on both deliveries and remained represented by one row in `stripe_events`. See [EVIDENCE.md](./EVIDENCE.md) for the recorded observations. Live forged-signature rejection has not been independently demonstrated.
## Alert outbox

Generation transactionally creates one alert record when API-call or AI-token
usage crosses 80% of the monthly limit. The database identity constraint
prevents repeated alerts for the same tenant, month, usage type, and threshold.

`app.services.alerts.process_one_alert()` claims pending work with PostgreSQL
`FOR UPDATE SKIP LOCKED`, delivers through an injectable notification adapter,
records delivery state, and retries transient failures up to three attempts.
`run_alert_worker()` processes a bounded number of alerts.

There is currently no standalone scheduler, console command, or worker process
entrypoint that runs continuously. Invoke one bounded batch explicitly:

```bash
.venv/bin/python -m app.jobs.alert_worker --max-alerts 100
```

The local adapter writes non-sensitive delivery records to application logs.
Terminal delivery failures are persisted as `failed` and emit a structured
failure log without including alert payloads, API keys, or payment data. A
production deployment may schedule this bounded command externally; no
scheduler is included.

## Tests and verification

Run formatting and lint checks:

```bash
.venv/bin/ruff format --check app tests
.venv/bin/ruff check app tests
git diff --check
```

Run the unit and integration suite:

```bash
.venv/bin/python -m pytest -q -rs
```

PostgreSQL integration tests require `TEST_DATABASE_URL` using the
`postgresql+psycopg` driver and the database name `flyrank_test`. For example,
export a locally constructed value in the shell without committing it:

```bash
export TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost:5432/flyrank_test'
.venv/bin/python -m pytest -q -rs
```

Latest local verification:

- four alert integration tests passed against local PostgreSQL
- the full PostgreSQL-backed suite reported `94 passed, 1 warning`
- the alert worker unit suite reported `5 passed`
- Alembic reported `No new upgrade operations detected.` at
  `20261016_0001 (head)`
- Ruff formatting/checks and `git diff --check` passed

The alert integration count and full-suite result were observed in the latest
local PostgreSQL-backed verification. Live Stripe test-mode Checkout and
webhook replay were verified; a separate live forged-signature HTTP probe
has not been recorded. See EVIDENCE.md for the acceptance status.

## Migrations

The initial migration creates tenants, API keys, plans, subscriptions, usage
events, Stripe events, quota state, and alert outbox tables with the required
foreign keys, uniqueness constraints, and checks. Verify migration state with:

```bash
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/alembic check
```

Do not reset the database or delete Docker volumes to apply migrations.

## Known limitations

- The alert worker does not run continuously by itself. Invoke the bounded worker command or configure an external scheduler.
- Live Stripe testing was performed in test mode. Live forged-signature rejection has automated test coverage, but a separate live forged-signature HTTP probe has not been recorded.
- The recorded live webhook replay confirms successful HTTP responses and a single stored Stripe event record. It does not independently establish that every possible downstream side effect is idempotent.
- See `EVIDENCE.md` for the distinction between automated test results, live test-mode observations, and evidence that remains outstanding.
