from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Plan

PLANS = (
    {
        "name": "Free",
        "api_call_limit": 1_000,
        "ai_token_limit": 100_000,
    },
    {
        "name": "Pro",
        "api_call_limit": 100_000,
        "ai_token_limit": 10_000_000,
    },
)


def seed_plans() -> None:
    session_factory = get_session_factory()

    with session_factory() as session:
        try:
            for plan_data in PLANS:
                plan = session.scalar(select(Plan).where(Plan.name == plan_data["name"]))

                if plan is None:
                    session.add(Plan(**plan_data))
                elif (
                    plan.api_call_limit != plan_data["api_call_limit"]
                    or plan.ai_token_limit != plan_data["ai_token_limit"]
                ):
                    raise ValueError(
                        f"Existing {plan_data['name']} plan has different limits. "
                        "Review it manually instead of overwriting it."
                    )

            session.commit()
            print("Free and Pro plans are present with the expected limits.")
        except Exception:
            session.rollback()
            raise


if __name__ == "__main__":
    seed_plans()
