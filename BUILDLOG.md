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
