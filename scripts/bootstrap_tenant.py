import argparse
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.api_keys import generate_api_key, hash_api_key
from app.db.session import get_session_factory
from app.models import ApiKey, Plan, Subscription, Tenant


def create_tenant(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Tenant name must not be empty.")

    session_factory = get_session_factory()
    api_key = generate_api_key()

    with session_factory() as session:
        try:
            free_plan = session.scalar(select(Plan).where(Plan.name == "Free"))

            if free_plan is None:
                raise RuntimeError(
                    "Free plan is missing. Run '.venv/bin/python -m scripts.seed_plans' first."
                )

            tenant = Tenant(name=name.strip())
            session.add(tenant)
            session.flush()

            session.add(
                ApiKey(
                    tenant_id=tenant.id,
                    key_hash=hash_api_key(api_key),
                    label="Initial bootstrap key",
                )
            )

            session.add(
                Subscription(
                    tenant_id=tenant.id,
                    plan_id=free_plan.id,
                    status="active",
                )
            )

            session.commit()
            return api_key

        except Exception:
            session.rollback()
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a tenant and issue its initial API key.")
    parser.add_argument(
        "--name",
        required=True,
        help="Tenant name",
    )
    args = parser.parse_args()

    name = args.name.strip()
    if not name:
        parser.error("--name must not be empty")

    try:
        api_key = create_tenant(name)
    except IntegrityError:
        print(
            "Could not create tenant because a database constraint was violated.",
            file=sys.stderr,
        )
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print("Tenant created successfully.")
    print("Copy this API key now; it will not be shown again:")
    print(api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
