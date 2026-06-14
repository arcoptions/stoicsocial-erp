"""Audit log view — paginated stock movement history."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.models import StockMovement
from core.security import inventory_access_required
from core.models import WebhookEvent


@login_required
@inventory_access_required
def audit_log(request: HttpRequest) -> HttpResponse:
    """Show paginated stock movement audit trail with optional pool/reason filter."""
    qs = StockMovement.objects.select_related(
        "blank_sku", "printed_sku__design", "actor"
    ).order_by("-created_at")

    pool = request.GET.get("pool", "").strip()
    reason = request.GET.get("reason", "").strip()

    if pool:
        qs = qs.filter(pool=pool)
    if reason:
        qs = qs.filter(reason=reason)

    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/audit_log.html",
        {
            "page_obj": page_obj,
            "pools": StockMovement.Pool.choices,
            "reasons": StockMovement.Reason.choices,
            "filters": {"pool": pool, "reason": reason},
        },
    )


@login_required
@inventory_access_required
def webhook_event_log(request: HttpRequest) -> HttpResponse:
    """Show recent Shopify webhook events received by BoldERP."""
    qs = WebhookEvent.objects.order_by("-created_at")

    topic = request.GET.get("topic", "").strip()
    if topic:
        qs = qs.filter(topic=topic)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    topics = list(WebhookEvent.objects.values_list("topic", flat=True).distinct().order_by("topic"))

    return render(
        request,
        "core/webhook_event_log.html",
        {
            "page_obj": page_obj,
            "topics": topics,
            "filters": {"topic": topic},
        },
    )
