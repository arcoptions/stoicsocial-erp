from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core.models import Order, OrderLine, PrintedSKU, WebhookEvent
from core.services import inventory


STATUS_RANK: dict[str, int] = {
    Order.STATUS_NEW: 0,
    Order.STATUS_NEEDS_PRINTING: 1,
    Order.STATUS_IN_PRINTING: 2,
    Order.STATUS_READY_TO_SHIP: 3,
    Order.STATUS_SHIPPED: 4,
    Order.STATUS_CANCELLED: 5,
}

LINE_TO_ORDER_STATUS: dict[str, str] = {
    OrderLine.STATUS_NEW: Order.STATUS_NEW,
    OrderLine.STATUS_TO_BE_PRINTED: Order.STATUS_NEEDS_PRINTING,
    OrderLine.STATUS_IN_PRINTING: Order.STATUS_IN_PRINTING,
    OrderLine.STATUS_READY_SHIP: Order.STATUS_READY_TO_SHIP,
    OrderLine.STATUS_SHIPPED: Order.STATUS_SHIPPED,
    OrderLine.STATUS_CANCELLED: Order.STATUS_CANCELLED,
}


def WORST_CASE(statuses: list[str], rank_map: dict[str, int]) -> str:
    """Return the worst status where the lowest non-terminal rank wins."""
    if not statuses:
        return Order.STATUS_ISSUE
    non_terminal = [status for status in statuses if status not in {Order.STATUS_SHIPPED, Order.STATUS_CANCELLED}]
    candidates = non_terminal or statuses
    return min(candidates, key=lambda status: rank_map.get(status, 999))


def verify_hmac(body: bytes, hmac_header: str) -> bool:
    """Verify Shopify HMAC using the configured API secret."""
    secret = getattr(settings, "SHOPIFY_API_SECRET", "") or getattr(settings, "SHOPIFY_WEBHOOK_SECRET", "")
    if not secret or not hmac_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, hmac_header)


def _parse_tags(raw_tags: Any) -> list[str]:
    """Normalize Shopify tag payload into a list of strings."""
    if raw_tags is None:
        return []
    if isinstance(raw_tags, list):
        return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    return [tag.strip() for tag in str(raw_tags).split(",") if tag.strip()]


def _to_int(value: Any, default: int = 0) -> int:
    """Coerce Shopify numeric values into integers."""
    if value in (None, ""):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(float(str(value).strip()))


def _resolve_printed_sku(item: dict[str, Any]) -> PrintedSKU | None:
    """Attempt to resolve a Shopify line item to a printed SKU."""
    query = PrintedSKU.objects.select_related("design")

    sku_id = item.get("sku")
    if sku_id:
        match = query.filter(id=str(sku_id)).first()
        if match:
            return match

    design_name = str(item.get("product_title") or item.get("title") or item.get("name") or "").strip()
    variant = str(item.get("variant_title") or item.get("option1") or "").strip() or None
    colour = str(item.get("option2") or item.get("color") or item.get("colour") or "").strip()
    size = str(item.get("option3") or item.get("size") or "").strip() or None

    filters: dict[str, Any] = {"design__name__iexact": design_name}
    if variant:
        filters["variant__iexact"] = variant
    else:
        filters["variant__isnull"] = True
    if colour:
        filters["colour__iexact"] = colour
    if size:
        filters["size__iexact"] = size

    return query.filter(**filters).first()


def _line_status_for_item(printed_sku: PrintedSKU | None, quantity: int) -> str:
    """Compute the line status based on printed stock availability."""
    if printed_sku is None:
        return OrderLine.STATUS_TO_BE_PRINTED
    return OrderLine.STATUS_READY_SHIP if printed_sku.available >= quantity else OrderLine.STATUS_TO_BE_PRINTED


def _normalize_fulfillment_status(value: Any) -> str:
    """Normalize Shopify fulfillment status strings for consistent branching."""
    return str(value or "").strip().lower()


def _extract_delivery_status(payload: dict[str, Any]) -> str:
    """Pick the most relevant delivery sub-status from a webhook payload."""
    for key in ("delivery_status", "shipment_status", "tracking_status"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_order_identifier_for_topic(topic: str, payload: dict[str, Any]) -> str:
    """Extract the Shopify order identifier required by each webhook topic."""
    if topic == "orders/fulfilled":
        return str(payload.get("order_id") or payload.get("id") or "").strip()
    return str(payload.get("id") or "").strip()


def _upsert_line(order: Order, item: dict[str, Any]) -> OrderLine | None:
    """Create or update an order line without applying inventory side effects yet."""
    shopify_line_id = str(item.get("id") or "").strip()
    if not shopify_line_id:
        return None

    quantity = _to_int(item.get("quantity"), default=0)
    printed_sku = _resolve_printed_sku(item)
    line, _ = OrderLine.objects.update_or_create(
        shopify_line_id=shopify_line_id,
        defaults={
            "order": order,
            "product_name": str(item.get("title") or item.get("name") or "Untitled").strip(),
            "variant": str(item.get("variant_title") or item.get("option1") or "").strip(),
            "size": str(item.get("size") or item.get("option3") or "").strip(),
            "quantity": quantity,
            "printed_sku": printed_sku,
            "is_bundle": False,
            "bundle_components": [],
        },
    )
    return line


def _set_line_to_be_printed(order_line: OrderLine) -> OrderLine:
    """Move a live line into the printing queue and release any existing reservation."""
    if order_line.status == OrderLine.STATUS_READY_SHIP:
        return inventory.release_printed(order_line)
    if order_line.status != OrderLine.STATUS_TO_BE_PRINTED:
        order_line.status = OrderLine.STATUS_TO_BE_PRINTED
        order_line.save(update_fields=["status", "updated_at"])
    return order_line


def _set_live_line_status(order_line: OrderLine) -> OrderLine:
    """Apply live-order line logic: ready-ship lines soft reserve, others go to printing."""
    target_status = _line_status_for_item(order_line.printed_sku, order_line.quantity)
    if target_status == OrderLine.STATUS_READY_SHIP:
        if order_line.status == OrderLine.STATUS_READY_SHIP:
            return order_line
        try:
            return inventory.reserve_printed(order_line)
        except ValueError:
            return _set_line_to_be_printed(order_line)
    return _set_line_to_be_printed(order_line)


def _mark_line_shipped(order_line: OrderLine, *, commit_reserved: bool) -> OrderLine:
    """Mark a line shipped, committing stock only when a live reservation actually exists."""
    if order_line.status == OrderLine.STATUS_SHIPPED:
        return order_line
    if (
        commit_reserved
        and order_line.printed_sku_id is not None
        and order_line.printed_sku.reserved >= order_line.quantity
        and order_line.printed_sku.on_hand >= order_line.quantity
    ):
        return inventory.commit_printed(order_line)
    order_line.status = OrderLine.STATUS_SHIPPED
    order_line.save(update_fields=["status", "updated_at"])
    return order_line


def _cancel_line(order_line: OrderLine) -> OrderLine:
    """Cancel a line and release any ready-to-ship reservation first."""
    if order_line.status == OrderLine.STATUS_READY_SHIP:
        order_line = inventory.release_printed(order_line)
    if order_line.status != OrderLine.STATUS_CANCELLED:
        order_line.status = OrderLine.STATUS_CANCELLED
        order_line.save(update_fields=["status", "updated_at"])
    return order_line


def _recompute_order(order: Order) -> str:
    """Recompute the worst-case order status from current line states."""
    order.status = WORST_CASE(
        [LINE_TO_ORDER_STATUS.get(status, Order.STATUS_NEW) for status in order.lines.values_list("status", flat=True)],
        STATUS_RANK,
    )
    order.save(update_fields=["status", "updated_at"])
    return order.status


def _apply_live_state_to_order(order: Order) -> str:
    """Re-evaluate a live order and ensure inconsistent rows are surfaced as issues."""
    live_lines = list(
        order.lines.select_related("printed_sku").exclude(
            status__in=[OrderLine.STATUS_CANCELLED, OrderLine.STATUS_SHIPPED],
        )
    )
    if not live_lines:
        order.status = Order.STATUS_ISSUE
        order.save(update_fields=["status", "updated_at"])
        return order.status

    for line in live_lines:
        if line.status in {
            OrderLine.STATUS_NEW,
            OrderLine.STATUS_TO_BE_PRINTED,
            OrderLine.STATUS_READY_SHIP,
        }:
            _set_live_line_status(line)

    recomputed = _recompute_order(order)
    if recomputed == Order.STATUS_NEW:
        order.status = Order.STATUS_ISSUE
        order.save(update_fields=["status", "updated_at"])
        return order.status
    return recomputed


def _reconcile_new_orders() -> int:
    """Process all currently New orders so they cannot remain unclassified."""
    new_orders = list(
        Order.objects.select_for_update().filter(status=Order.STATUS_NEW).order_by("created_at")
    )
    for order in new_orders:
        _apply_live_state_to_order(order)
    return len(new_orders)


@transaction.atomic
def ingest_order(payload: dict[str, Any]) -> Order:
    """Upsert an order and its lines from a Shopify order webhook payload."""
    shopify_order_id = str(payload.get("id") or "").strip()
    if not shopify_order_id:
        raise ValueError("Shopify order id is required for order ingestion.")
    existing_order = Order.objects.select_for_update().filter(shopify_order_id=shopify_order_id).first()
    incoming_fulfillment_status = _normalize_fulfillment_status(payload.get("fulfillment_status"))
    fulfillment_status = incoming_fulfillment_status or _normalize_fulfillment_status(
        existing_order.shopify_fulfillment_status if existing_order is not None else ""
    )
    delivery_status = _extract_delivery_status(payload) or (
        existing_order.shopify_delivery_status if existing_order is not None else ""
    )
    order, _ = Order.objects.select_for_update().update_or_create(
        shopify_order_id=shopify_order_id,
        defaults={
            "order_no": str(payload.get("name") or payload.get("order_number") or "").strip(),
            "customer_name": str((payload.get("customer") or {}).get("first_name") or "").strip() + (
                f" {str((payload.get('customer') or {}).get('last_name') or '').strip()}" if (payload.get("customer") or {}).get("last_name") else ""
            ),
            "email": str(payload.get("email") or "").strip(),
            "tags": _parse_tags(payload.get("tags")),
            "shopify_fulfillment_status": fulfillment_status,
            "shopify_delivery_status": delivery_status,
            "raw_payload": payload,
        },
    )

    seen_line_ids: set[str] = set()
    for item in payload.get("line_items", []):
        line = _upsert_line(order, item)
        if line is None:
            continue
        seen_line_ids.add(line.shopify_line_id)
        if fulfillment_status == "fulfilled":
            _mark_line_shipped(line, commit_reserved=False)
        else:
            _set_live_line_status(line)

    if seen_line_ids:
        for stale_line in order.lines.exclude(shopify_line_id__in=seen_line_ids):
            _cancel_line(stale_line)

    if fulfillment_status == "fulfilled":
        order.status = Order.STATUS_SHIPPED
        order.save(update_fields=["status", "updated_at"])
    else:
        _apply_live_state_to_order(order)
    return order


@transaction.atomic
def mark_cancelled(payload: dict[str, Any]) -> None:
    """Mark a Shopify order and all of its lines as cancelled."""
    order_id = str(payload.get("id") or "").strip()
    if not order_id:
        raise ValueError("Shopify order id is required for cancellation sync.")
    order = Order.objects.select_for_update().filter(shopify_order_id=order_id).first()
    if order is None:
        return
    for line in order.lines.all():
        _cancel_line(line)
    order.status = Order.STATUS_CANCELLED
    order.raw_payload = payload
    order.save(update_fields=["status", "raw_payload", "updated_at"])


@transaction.atomic
def sync_fulfillment(payload: dict[str, Any]) -> None:
    """Sync Shopify fulfillment state onto the internal order record."""
    order_identifier = str(payload.get("order_id") or payload.get("id") or "").strip()
    if not order_identifier:
        raise ValueError("Shopify order id is required for fulfillment sync.")
    order = Order.objects.select_for_update().filter(shopify_order_id=order_identifier).first()
    if order is None:
        return
    fulfillment_status = _normalize_fulfillment_status(payload.get("fulfillment_status") or payload.get("status"))
    order.shopify_fulfillment_status = fulfillment_status
    order.shopify_delivery_status = _extract_delivery_status(payload) or order.shopify_delivery_status
    order.raw_payload = payload
    fulfilled_line_ids = {
        str(item.get("id") or "").strip() for item in payload.get("line_items", []) if str(item.get("id") or "").strip()
    }

    target_lines = order.lines.exclude(status=OrderLine.STATUS_CANCELLED)
    if fulfilled_line_ids:
        target_lines = target_lines.filter(shopify_line_id__in=fulfilled_line_ids)

    if fulfillment_status == "fulfilled":
        for line in target_lines:
            _mark_line_shipped(line, commit_reserved=True)
    _recompute_order(order)

    non_cancelled = order.lines.exclude(status=OrderLine.STATUS_CANCELLED)
    if non_cancelled.exists() and not non_cancelled.exclude(status=OrderLine.STATUS_SHIPPED).exists():
        order.status = Order.STATUS_SHIPPED

    order.save(
        update_fields=["shopify_fulfillment_status", "shopify_delivery_status", "raw_payload", "status", "updated_at"]
    )


@transaction.atomic
def ingest_shopify_webhook(topic: str, idempotency_key: str, payload: dict[str, Any]) -> WebhookEvent:
    """Persist a Shopify webhook event and dispatch to the matching domain handler."""
    event, created = WebhookEvent.objects.select_for_update().get_or_create(
        source="shopify",
        topic=topic,
        idempotency_key=idempotency_key,
        defaults={"payload": payload},
    )
    if not created and event.processed_at is not None:
        return event

    if topic in {"orders/create", "orders/updated"}:
        ingest_order(payload)
    elif topic == "orders/cancelled":
        mark_cancelled(payload)
    elif topic == "orders/fulfilled":
        sync_fulfillment(payload)

    _reconcile_new_orders()

    event.payload = payload
    event.processed_at = timezone.now()
    event.save(update_fields=["payload", "processed_at", "updated_at"])
    return event


@csrf_exempt
def shopify_webhook(request: HttpRequest) -> HttpResponse:
    """Accept Shopify webhooks and process through Django-Q2 (async) or synchronously as fallback."""
    from core.tasks import enqueue_shopify_webhook, process_shopify_webhook

    if request.method != "POST":
        return HttpResponse(status=405)

    topic = request.headers.get("X-Shopify-Topic", "")
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "") or f"{topic}:{request.headers.get('X-Shopify-Order-Id', '')}"
    body = request.body

    if not verify_hmac(body, hmac_header):
        return JsonResponse({"detail": "Invalid signature"}, status=401)

    payload = json.loads(body.decode("utf-8") or "{}")
    if topic in {"orders/create", "orders/updated", "orders/cancelled", "orders/fulfilled"}:
        if not _extract_order_identifier_for_topic(topic, payload):
            return JsonResponse({"detail": "Missing Shopify order id"}, status=400)
    
    # Try async queueing via Django-Q2; fall back to sync if not available
    try:
        enqueue_shopify_webhook(topic, webhook_id, payload)
        return JsonResponse({"queued": True}, status=202)
    except Exception:
        # Worker not available; process synchronously
        try:
            process_shopify_webhook(topic, webhook_id, payload)
            return JsonResponse({"processed": True}, status=200)
        except Exception as exc:
            return JsonResponse({"detail": str(exc)}, status=500)


def verify_shopify_hmac(raw_body: bytes, provided_hmac: str) -> bool:
    """Compatibility wrapper for the previous verifier name."""
    return verify_hmac(raw_body, provided_hmac)


def recompute_order_status(order_id: str) -> str:
    """Compatibility helper to recalculate order status from current line states."""
    order = Order.objects.get(id=order_id)
    return _recompute_order(order)


shopify_webhook_view = shopify_webhook
