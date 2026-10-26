import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.alert import AlertOutbox

ALERT_THRESHOLD_PERCENT = 80
MAX_DELIVERY_ATTEMPTS = 3
CLAIM_TIMEOUT = timedelta(minutes=10)
logger = logging.getLogger(__name__)


class NotificationAdapter(Protocol):
    def deliver(
        self,
        *,
        notification_id: UUID,
        tenant_id: UUID,
        usage_type: str,
        payload: dict[str, Any],
    ) -> None: ...


class TransientDeliveryError(Exception):
    """A delivery failure that may succeed on a later attempt."""


class PermanentDeliveryError(Exception):
    """A delivery failure that must not be retried."""


class LoggingNotificationAdapter:
    """Local adapter that emits non-sensitive delivery records to application logs."""

    def deliver(
        self,
        *,
        notification_id: UUID,
        tenant_id: UUID,
        usage_type: str,
        payload: dict[str, Any],
    ) -> None:
        del payload
        logger.info(
            "Usage threshold alert delivered",
            extra={
                "notification_id": str(notification_id),
                "tenant_id": str(tenant_id),
                "usage_type": usage_type,
            },
        )


def enqueue_threshold_alerts(
    db: Session,
    *,
    tenant_id: UUID,
    billing_month,
    previous_api_calls: int,
    current_api_calls: int,
    api_call_limit: int,
    previous_ai_tokens: int,
    current_ai_tokens: int,
    ai_token_limit: int,
) -> None:
    candidates = (
        ("api_calls", previous_api_calls, current_api_calls, api_call_limit),
        ("ai_tokens", previous_ai_tokens, current_ai_tokens, ai_token_limit),
    )
    for usage_type, previous, current, limit in candidates:
        if limit <= 0:
            continue
        crossed = previous * 100 < limit * ALERT_THRESHOLD_PERCENT and current * 100 >= (
            limit * ALERT_THRESHOLD_PERCENT
        )
        if not crossed:
            continue

        db.execute(
            pg_insert(AlertOutbox)
            .values(
                tenant_id=tenant_id,
                billing_month=billing_month,
                usage_type=usage_type,
                threshold=ALERT_THRESHOLD_PERCENT,
                payload={
                    "billing_month": billing_month.isoformat(),
                    "threshold": ALERT_THRESHOLD_PERCENT,
                    "usage_type": usage_type,
                    "used": current,
                    "limit": limit,
                },
                status="pending",
                attempts=0,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "billing_month", "usage_type", "threshold"]
            )
        )


def _claim_alert(db: Session) -> AlertOutbox | None:
    now = datetime.now(UTC)
    stale_processing = now - CLAIM_TIMEOUT
    with db.begin():
        alert = db.scalar(
            select(AlertOutbox)
            .where(
                AlertOutbox.status.in_(["pending", "retry"]),
                or_(
                    AlertOutbox.available_at.is_(None),
                    AlertOutbox.available_at <= now,
                ),
            )
            .order_by(AlertOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if alert is None:
            alert = db.scalar(
                select(AlertOutbox)
                .where(
                    AlertOutbox.status == "processing",
                    AlertOutbox.updated_at <= stale_processing,
                )
                .order_by(AlertOutbox.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        if alert is None:
            return None
        alert.status = "processing"
        alert.attempts += 1
        alert.last_error = None
        db.flush()
        return alert


def _record_delivery_success(db: Session, alert_id: UUID) -> None:
    with db.begin():
        alert = db.scalar(select(AlertOutbox).where(AlertOutbox.id == alert_id).with_for_update())
        if alert is None or alert.status == "delivered":
            return
        alert.status = "delivered"
        alert.delivered_at = datetime.now(UTC)


def _record_delivery_failure(
    db: Session,
    *,
    alert_id: UUID,
    error: Exception,
    retryable: bool,
) -> None:
    with db.begin():
        alert = db.scalar(select(AlertOutbox).where(AlertOutbox.id == alert_id).with_for_update())
        if alert is None or alert.status == "delivered":
            return
        alert.last_error = str(error)[:1024]
        if not retryable or alert.attempts >= MAX_DELIVERY_ATTEMPTS:
            alert.status = "failed"
            alert.available_at = None
            logger.error(
                "Usage threshold alert delivery permanently failed",
                extra={
                    "alert_id": str(alert.id),
                    "tenant_id": str(alert.tenant_id),
                    "attempts": alert.attempts,
                },
            )
        else:
            alert.status = "retry"
            alert.available_at = datetime.now(UTC) + timedelta(seconds=2**alert.attempts)


def process_one_alert(db: Session, adapter: NotificationAdapter) -> bool:
    alert = _claim_alert(db)
    if alert is None:
        return False

    try:
        adapter.deliver(
            notification_id=alert.id,
            tenant_id=alert.tenant_id,
            usage_type=alert.usage_type,
            payload=alert.payload,
        )
    except TransientDeliveryError as exc:
        _record_delivery_failure(db, alert_id=alert.id, error=exc, retryable=True)
    except PermanentDeliveryError as exc:
        _record_delivery_failure(db, alert_id=alert.id, error=exc, retryable=False)
    else:
        _record_delivery_success(db, alert.id)
    return True


def run_alert_worker(
    db: Session,
    adapter: NotificationAdapter,
    *,
    max_alerts: int | None = None,
) -> int:
    processed = 0
    while max_alerts is None or processed < max_alerts:
        if not process_one_alert(db, adapter):
            break
        processed += 1
    return processed
