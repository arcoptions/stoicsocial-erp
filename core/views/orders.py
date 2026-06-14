"""Order list and detail views for inventory managers."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import Order, OrderLine
from core.security import inventory_access_required

SIZE_ORDER = ["S", "M", "L", "XL", "2XL", "3XL"]


def _size_sort_key(size: str) -> tuple[int, str]:
    normalized = (size or "NA").upper()
    if normalized in SIZE_ORDER:
        return (SIZE_ORDER.index(normalized), normalized)
    return (len(SIZE_ORDER), normalized)


def _build_dashboard_stats() -> dict:
    """Compute dashboard KPIs shown at the top of the orders page."""
    now = timezone.now()
    all_orders = Order.objects.all()

    total = all_orders.count()
    new_count = all_orders.filter(status=Order.STATUS_NEW).count()
    needs_printing = all_orders.filter(status=Order.STATUS_NEEDS_PRINTING).count()
    in_printing = all_orders.filter(status=Order.STATUS_IN_PRINTING).count()
    ready_to_ship = all_orders.filter(status=Order.STATUS_READY_TO_SHIP).count()
    shipped = all_orders.filter(status=Order.STATUS_SHIPPED).count()
    cancelled = all_orders.filter(status=Order.STATUS_CANCELLED).count()
    actionable = needs_printing + in_printing + ready_to_ship

    # Orders stuck ≥ 3 days without reaching shipped/cancelled
    stale_threshold = now - timezone.timedelta(days=3)
    stale = all_orders.filter(
        created_at__lte=stale_threshold,
    ).exclude(
        status__in=[Order.STATUS_SHIPPED, Order.STATUS_CANCELLED],
    ).count()

    # Orders stuck ≥ 7 days (urgent)
    urgent_threshold = now - timezone.timedelta(days=7)
    urgent = all_orders.filter(
        created_at__lte=urgent_threshold,
    ).exclude(
        status__in=[Order.STATUS_SHIPPED, Order.STATUS_CANCELLED],
    ).count()

    return {
        "total": total,
        "new": new_count,
        "needs_printing": needs_printing,
        "in_printing": in_printing,
        "ready_to_ship": ready_to_ship,
        "shipped": shipped,
        "cancelled": cancelled,
        "actionable": actionable,
        "stale": stale,
        "urgent": urgent,
    }


@login_required
@inventory_access_required
def order_list(request: HttpRequest) -> HttpResponse:
    """Show all orders with combined status/tag/date/search/SKU filters."""
    qs = (
        Order.objects.annotate(line_count=Count("lines"))
        .order_by("-created_at")
    )

    status = request.GET.get("status", "").strip()
    age = request.GET.get("age", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    q = request.GET.get("q", "").strip()
    sku = request.GET.get("sku", "").strip()

    if status:
        qs = qs.filter(status=status)
    if age in {"stale", "urgent"}:
        threshold_days = 7 if age == "urgent" else 3
        threshold = timezone.now() - timezone.timedelta(days=threshold_days)
        qs = qs.filter(created_at__lte=threshold).exclude(
            status__in=[Order.STATUS_SHIPPED, Order.STATUS_CANCELLED],
        )
    if date_from:
        parsed = parse_date(date_from)
        if parsed:
            qs = qs.filter(created_at__date__gte=parsed)
    if date_to:
        parsed = parse_date(date_to)
        if parsed:
            qs = qs.filter(created_at__date__lte=parsed)
    if q:
        qs = qs.filter(
            Q(order_no__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(email__icontains=q)
            | Q(shopify_order_id__icontains=q)
        )
    if sku:
        qs = qs.filter(
            Q(lines__product_name__icontains=sku)
            | Q(lines__printed_sku__design__name__icontains=sku)
            | Q(lines__variant__icontains=sku)
            | Q(lines__size__icontains=sku)
        ).distinct()

    return render(
        request,
        "core/orders.html",
        {
            "orders": qs,
            "statuses": Order.Status.choices,
            "filters": {
                "status": status,
                "age": age,
                "date_from": date_from,
                "date_to": date_to,
                "q": q,
                "sku": sku,
            },
            "stats": _build_dashboard_stats(),
        },
    )


@login_required
@inventory_access_required
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    """Show a single order with all line items and their per-line status."""
    order = get_object_or_404(
        Order.objects.prefetch_related(
            Prefetch(
                "lines",
                queryset=OrderLine.objects.select_related(
                    "printed_sku__design"
                ).order_by("created_at"),
            )
        ),
        id=order_id,
    )

    # Group lines by status for a quick summary
    status_counts: dict[str, int] = {}
    grouped_lines: dict[tuple[str, str, str], dict[str, object]] = {}
    sizes_seen: set[str] = set()
    for line in order.lines.all():
        status_counts[line.status] = status_counts.get(line.status, 0) + 1
        size_label = line.size or "NA"
        sizes_seen.add(size_label)
        key = (
            line.product_name,
            line.variant or "BASE",
            line.printed_sku.colour if line.printed_sku_id else "—",
        )
        row = grouped_lines.setdefault(
            key,
            {
                "product_name": line.product_name,
                "variant": line.variant or "BASE",
                "colour": line.printed_sku.colour if line.printed_sku_id else "—",
                "size_qty": {},
                "statuses": [],
                "printed_sku": line.printed_sku,
            },
        )
        size_qty = row["size_qty"]
        if isinstance(size_qty, dict):
            size_qty[size_label] = int(size_qty.get(size_label, 0)) + line.quantity
        statuses = row["statuses"]
        if isinstance(statuses, list) and line.get_status_display() not in statuses:
            statuses.append(line.get_status_display())

    ordered_sizes = sorted(sizes_seen, key=_size_sort_key)
    grouped_line_rows: list[dict[str, object]] = []
    for row in grouped_lines.values():
        size_qty = row["size_qty"]
        row["size_cells"] = [size_qty.get(size, 0) if isinstance(size_qty, dict) else 0 for size in ordered_sizes]
        grouped_line_rows.append(row)

    grouped_line_rows.sort(key=lambda row: (str(row["product_name"]), str(row["variant"]), str(row["colour"])))

    return render(
        request,
        "core/order_detail.html",
        {
            "order": order,
            "status_counts": status_counts,
            "line_statuses": OrderLine.Status.choices,
            "sizes": ordered_sizes,
            "grouped_lines": grouped_line_rows,
        },
    )


@login_required
@inventory_access_required
@require_POST
def order_bulk_action(request: HttpRequest) -> HttpResponse:
    """Handle bulk status changes on selected orders."""
    action = request.POST.get("action", "").strip()
    order_ids = request.POST.getlist("order_ids")

    if not order_ids:
        messages.error(request, "No orders selected.")
        return redirect(request.POST.get("next", "order-list"))

    ALLOWED_ACTIONS = {
        "mark_shipped": Order.STATUS_SHIPPED,
        "mark_cancelled": Order.STATUS_CANCELLED,
        "mark_needs_printing": Order.STATUS_NEEDS_PRINTING,
    }

    if action not in ALLOWED_ACTIONS:
        messages.error(request, f"Unknown action: {action}")
        return redirect(request.POST.get("next", "order-list"))

    new_status = ALLOWED_ACTIONS[action]

    with transaction.atomic():
        orders = Order.objects.select_for_update().filter(id__in=order_ids)
        updated = 0
        for order in orders:
            if new_status == Order.STATUS_SHIPPED:
                order.lines.exclude(status=OrderLine.STATUS_CANCELLED).update(
                    status=OrderLine.STATUS_SHIPPED, updated_at=timezone.now()
                )
            order.status = new_status
            order.save(update_fields=["status", "updated_at"])
            updated += 1

    messages.success(request, f"{updated} order(s) updated to '{new_status}'.")
    next_url = request.POST.get("next", "")
    if next_url:
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(next_url)
    return redirect("order-list")
