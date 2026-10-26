"""Runnable bounded alert-outbox worker."""

import argparse

from app.db.session import get_session_factory
from app.services.alerts import LoggingNotificationAdapter, run_alert_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Process pending usage-threshold alerts.")
    parser.add_argument(
        "--max-alerts",
        type=int,
        default=100,
        help="Maximum number of alerts to process before exiting (default: 100).",
    )
    args = parser.parse_args()
    if args.max_alerts < 1:
        parser.error("--max-alerts must be at least 1")

    with get_session_factory()() as session:
        processed = run_alert_worker(
            session,
            LoggingNotificationAdapter(),
            max_alerts=args.max_alerts,
        )
    print(f"Processed {processed} alert(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
