# FlyRank Capstone — Copilot Instructions

## Project
Build a production-minded LLM Usage Metering & Billing Service using FastAPI, PostgreSQL, SQLAlchemy, Alembic, and Stripe test mode.

## Existing architecture
- API routes: `app/api/routes/`
- Request/response schemas: `app/schemas/`
- Business logic: `app/services/`
- SQLAlchemy models: `app/models/`
- Database session: `app/db/session.py`
- Configuration: `app/core/config.py`
- Tests: `tests/unit/` and `tests/integration/`
- Design requirements: `docs/design.md`
- Build history: `BUILDLOG.md`

## Required practices
- Inspect existing files and `docs/design.md` before implementing features.
- Reuse existing patterns and dependencies; avoid unnecessary rewrites.
- Preserve tenant isolation and authenticate tenant access using API keys.
- Never store or log raw API keys, Stripe secrets, or other credentials.
- Verify Stripe webhook signatures before processing events.
- Handle duplicate webhook deliveries and event ordering safely.
- Use database transactions for subscription and metering state changes.
- Use integer arithmetic for billing calculations.
- Add tests for success cases, failures, security, and edge cases.
- Keep migrations consistent with SQLAlchemy models.
- Do not remove existing tests or weaken assertions to make tests pass.
- Do not modify `.env`, expose secrets, reset databases, or delete database volumes.
- Do not commit, push, or deploy without explicit user approval.

## Verification
Run:
- `ruff format app tests`
- `ruff check app tests`
- `.venv/bin/python -m pytest -q`

Report changed files, migration requirements, commands run, test results, and unresolved risks. Do not claim tests passed unless they were actually run.
