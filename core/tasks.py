from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import async_task

from core.models import PrintedSKU
from core.services import shopify

try:
    import sentry_sdk
except Exception:  # pragma: no cover - optional dependency at runtime
    sentry_sdk = None


def _capture_exception(exc: Exception) -> None:
    """Report an exception to Sentry when configured."""
    if sentry_sdk is not None:
        sentry_sdk.capture_exception(exc)


def process_shopify_webhook(topic: str, idempotency_key: str, payload: dict[str, Any]) -> str:
    """Dispatch a Shopify webhook payload through the persisted idempotent handler."""
    try:
        with transaction.atomic():
            event = shopify.ingest_shopify_webhook(topic, idempotency_key, payload)
            return str(event.id)
    except Exception as exc:
        _capture_exception(exc)
        raise


def _build_low_stock_message(low_stock_skus: list[PrintedSKU]) -> str:
    """Format the low-stock alert body for push and email delivery."""
    lines = ["BoldERP low stock alert", ""]
    for sku in low_stock_skus:
        lines.append(
            f"- {sku}: available={sku.available}, min={sku.buffer_min}, target={sku.buffer_target}"
        )
    return "\n".join(lines)


def _send_ntfy_push(message: str) -> None:
    """Send a low-stock push notification to ntfy.sh when configured."""
    topic = getattr(settings, "NTFY_TOPIC", "")
    if not topic:
        return
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            f"https://ntfy.sh/{topic}",
            content=message.encode("utf-8"),
            headers={"Title": "BoldERP Low Stock", "Tags": "warning,inventory"},
        )
        response.raise_for_status()


def _send_resend_email(message: str) -> None:
    """Send a low-stock alert email via Resend when credentials are configured."""
    api_key = getattr(settings, "RESEND_API_KEY", "")
    recipient = getattr(settings, "OPS_EMAIL_TO", "")
    if not api_key or not recipient:
        return
    from_email = getattr(settings, "RESEND_FROM_EMAIL", "ops@bolderp.local")
    payload = {
        "from": from_email,
        "to": [recipient],
        "subject": "BoldERP low stock alert",
        "text": message,
    }
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()


def low_stock_check() -> int:
    """Find low-stock printed SKUs and send ntfy/resend alerts.

    This task is idempotent for stock state because it only reads inventory and sends
    notifications for the current snapshot.
    """
    try:
        low_stock_skus = list(
            PrintedSKU.objects.select_related("design")
            .all()
            .order_by("design__name", "colour", "size")
        )
        low_stock_skus = [sku for sku in low_stock_skus if sku.available < sku.buffer_min]
        if not low_stock_skus:
            return 0
        message = _build_low_stock_message(low_stock_skus)
        _send_ntfy_push(message)
        _send_resend_email(message)
        return len(low_stock_skus)
    except Exception as exc:
        _capture_exception(exc)
        raise


def schedule_low_stock_check_daily() -> Schedule:
    """Ensure a daily Django-Q2 schedule exists for `low_stock_check` at 09:00 IST."""
    tz = timezone.get_current_timezone()
    now_local = timezone.localtime(timezone.now(), tz)
    next_run_local = datetime.combine(now_local.date(), time(hour=9, minute=0))
    next_run = timezone.make_aware(next_run_local, tz) if timezone.is_naive(next_run_local) else next_run_local
    if next_run <= now_local:
        next_run = next_run + timedelta(days=1)
    schedule, _ = Schedule.objects.update_or_create(
        name="daily-low-stock-check",
        defaults={
            "func": "core.tasks.low_stock_check",
            "schedule_type": Schedule.DAILY,
            "next_run": next_run,
            "repeats": -1,
        },
    )
    return schedule


LOW_STOCK_SCHEDULE_SNIPPET = """
from core.tasks import schedule_low_stock_check_daily

schedule_low_stock_check_daily()
""".strip()


def enqueue_shopify_webhook(topic: str, idempotency_key: str, payload: dict[str, Any]) -> str:
    """Queue Shopify webhook processing for burst traffic handling."""
    return async_task(process_shopify_webhook, topic, idempotency_key, payload)
