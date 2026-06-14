from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Sum, Value, When
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.models import Order, PrintedSKU
from core.security import inventory_access_required

SIZE_ORDER = ["S", "M", "L", "XL", "2XL", "3XL"]


def _size_sort_key(size: str) -> tuple[int, str]:
    """Sort known apparel sizes first, then any custom sizes alphabetically."""
    normalized = (size or "NA").upper()
    if normalized in SIZE_ORDER:
        return (SIZE_ORDER.index(normalized), normalized)
    return (len(SIZE_ORDER), normalized)


@login_required
@inventory_access_required
def forecast(request: HttpRequest) -> HttpResponse:
    """Render grouped forecast rows with size availability shown in columns."""
    now = timezone.now()
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)
    cutoff_90 = now - timedelta(days=90)

    sku_rows = (
        PrintedSKU.objects.select_related("design")
        .annotate(
            units_7d=Sum(
                Case(
                    When(
                        order_lines__order__status=Order.STATUS_SHIPPED,
                        order_lines__order__updated_at__gte=cutoff_7,
                        then="order_lines__quantity",
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
            units_30d=Sum(
                Case(
                    When(
                        order_lines__order__status=Order.STATUS_SHIPPED,
                        order_lines__order__updated_at__gte=cutoff_30,
                        then="order_lines__quantity",
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
            units_90d=Sum(
                Case(
                    When(
                        order_lines__order__status=Order.STATUS_SHIPPED,
                        order_lines__order__updated_at__gte=cutoff_90,
                        then="order_lines__quantity",
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by("design__name", "colour", "size")
    )

    grouped_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    sizes_seen: set[str] = set()

    for sku in sku_rows:
        units_7d = int(sku.units_7d or 0)
        units_30d = int(sku.units_30d or 0)
        units_90d = int(sku.units_90d or 0)
        available = sku.available
        daily_rate_30d = units_30d / 30 if units_30d > 0 else 0
        key = (sku.design.name, sku.variant or "BASE", sku.colour)
        size_label = sku.size or "NA"
        sizes_seen.add(size_label)

        row = grouped_rows.setdefault(
            key,
            {
                "design_name": sku.design.name,
                "variant": sku.variant or "BASE",
                "colour": sku.colour,
                "size_available": {},
                "units_7d": 0,
                "units_30d": 0,
                "units_90d": 0,
                "available_total": 0,
                "buffer_min_total": 0,
                "buffer_target_total": 0,
                "buffer_max_total": 0,
            },
        )
        row["size_available"][size_label] = available
        row["units_7d"] += units_7d
        row["units_30d"] += units_30d
        row["units_90d"] += units_90d
        row["available_total"] += available
        row["buffer_min_total"] += sku.buffer_min
        row["buffer_target_total"] += sku.buffer_target
        row["buffer_max_total"] += sku.buffer_max

    rows: list[dict[str, Any]] = []
    for row in grouped_rows.values():
        daily_rate_30d = row["units_30d"] / 30 if row["units_30d"] > 0 else 0
        days_of_stock = round(row["available_total"] / daily_rate_30d, 1) if daily_rate_30d > 0 else None
        row["days_of_stock"] = days_of_stock
        row["is_risk"] = row["available_total"] < row["buffer_min_total"] or (
            days_of_stock is not None and days_of_stock < 14
        )
        rows.append(row)

    rows.sort(key=lambda row: row["days_of_stock"] if row["days_of_stock"] is not None else float("inf"))
    ordered_sizes = sorted(sizes_seen, key=_size_sort_key)
    for row in rows:
        row["size_cells"] = [row["size_available"].get(size, 0) for size in ordered_sizes]
    return render(request, "core/forecast.html", {"rows": rows, "sizes": ordered_sizes})


forecast_view = forecast
