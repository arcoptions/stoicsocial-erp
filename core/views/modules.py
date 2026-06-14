from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import Order, OrderLine
from core.security import finance_access_required, sales_access_required


@dataclass
class SalesInsights:
    total_orders: int
    orders_today: int
    orders_this_month: int
    units_sold: int
    unique_customers: int
    recurring_customers: int
    recurring_rate: float
    cancelled_orders: int
    cancelled_rate: float
    return_exchange_orders: int
    return_exchange_rate: float
    revenue_paise: int
    revenue_coverage_count: int
    revenue_coverage_rate: float
    aov_paise: int


def _money_to_paise(value: Any) -> int | None:
    """Convert rupee-like values from payload into paise."""
    if value in {None, ""}:
        return None
    normalized = str(value).replace(",", "").strip()
    try:
        return int((Decimal(normalized) * 100).quantize(Decimal("1")))
    except InvalidOperation:
        return None


def _paise_to_rupees(value: int) -> float:
    """Convert paise to rupees for display."""
    return value / 100


def _extract_order_revenue_paise(order: Order) -> int | None:
    """Extract revenue from known Shopify payload fields."""
    payload = order.raw_payload or {}
    for key in ["current_total_price", "total_price", "current_subtotal_price", "subtotal_price"]:
        amount = _money_to_paise(payload.get(key))
        if amount is not None:
            return amount
    return None


def _extract_customer_key(order: Order) -> str | None:
    """Build a stable customer identifier for repeat-customer analytics."""
    if order.email:
        return order.email.strip().lower()

    payload = order.raw_payload or {}
    customer = payload.get("customer") or {}
    customer_id = customer.get("id")
    if customer_id:
        return f"shopify:{customer_id}"

    if order.customer_name:
        return f"name:{order.customer_name.strip().lower()}"
    return None


def _is_return_or_exchange(order: Order) -> bool:
    """Infer return or exchange from status, tags, and payload hints."""
    payload = order.raw_payload or {}
    tags = [str(tag).lower() for tag in (order.tags or [])]
    tag_text = " ".join(tags)
    reason_parts = [
        str(payload.get("cancel_reason", "")).lower(),
        str(payload.get("note", "")).lower(),
        str(payload.get("source", "")).lower(),
        tag_text,
    ]
    reason_text = " ".join(reason_parts)

    keywords = ["return", "refund", "exchange", "replacement", "rto"]
    if any(keyword in reason_text for keyword in keywords):
        return True

    if order.status == Order.STATUS_ISSUE and any(keyword in tag_text for keyword in keywords):
        return True
    return False


def _first_day_of_month(day: date) -> date:
    """Return the month start date for a given day."""
    return day.replace(day=1)


def _compute_insights(
    orders: list[Order],
    line_qs: Any,
    total_orders: int,
) -> SalesInsights:
    """Compute summary sales KPIs for the selected filter window."""
    today = timezone.localdate()
    month_start = _first_day_of_month(today)

    orders_today = sum(1 for order in orders if timezone.localtime(order.created_at).date() == today)
    orders_this_month = sum(
        1 for order in orders if timezone.localtime(order.created_at).date() >= month_start
    )

    units_sold = (
        line_qs.exclude(status=OrderLine.STATUS_CANCELLED).aggregate(total=Sum("quantity"))["total"] or 0
    )

    customer_counter: Counter[str] = Counter()
    for order in orders:
        customer_key = _extract_customer_key(order)
        if customer_key:
            customer_counter[customer_key] += 1

    unique_customers = len(customer_counter)
    recurring_customers = sum(1 for _, count in customer_counter.items() if count > 1)
    recurring_rate = (recurring_customers / unique_customers * 100) if unique_customers else 0.0

    cancelled_orders = sum(1 for order in orders if order.status == Order.STATUS_CANCELLED)
    cancelled_rate = (cancelled_orders / total_orders * 100) if total_orders else 0.0

    return_exchange_orders = sum(1 for order in orders if _is_return_or_exchange(order))
    return_exchange_rate = (return_exchange_orders / total_orders * 100) if total_orders else 0.0

    revenue_paise = 0
    revenue_coverage_count = 0
    for order in orders:
        amount = _extract_order_revenue_paise(order)
        if amount is not None:
            revenue_paise += amount
            revenue_coverage_count += 1

    revenue_coverage_rate = (revenue_coverage_count / total_orders * 100) if total_orders else 0.0
    aov_paise = int(revenue_paise / revenue_coverage_count) if revenue_coverage_count else 0

    return SalesInsights(
        total_orders=total_orders,
        orders_today=orders_today,
        orders_this_month=orders_this_month,
        units_sold=units_sold,
        unique_customers=unique_customers,
        recurring_customers=recurring_customers,
        recurring_rate=recurring_rate,
        cancelled_orders=cancelled_orders,
        cancelled_rate=cancelled_rate,
        return_exchange_orders=return_exchange_orders,
        return_exchange_rate=return_exchange_rate,
        revenue_paise=revenue_paise,
        revenue_coverage_count=revenue_coverage_count,
        revenue_coverage_rate=revenue_coverage_rate,
        aov_paise=aov_paise,
    )


def _build_recommendations(
    insights: SalesInsights,
    top_products: list[dict[str, Any]],
) -> list[str]:
    """Generate actionable recommendations from computed metrics."""
    recommendations: list[str] = []

    if insights.cancelled_rate >= 10:
        recommendations.append(
            f"Cancellation rate is {insights.cancelled_rate:.1f}%. Review order confirmation and fulfillment SLAs to reduce drop-offs."
        )
    if insights.recurring_rate < 25 and insights.unique_customers > 0:
        recommendations.append(
            f"Repeat customer rate is {insights.recurring_rate:.1f}%. Introduce retention campaigns and post-purchase offers."
        )
    if insights.return_exchange_rate >= 5:
        recommendations.append(
            f"Return or exchange signals are at {insights.return_exchange_rate:.1f}%. Audit size guidance and quality control for top-return SKUs."
        )
    if insights.revenue_coverage_rate < 70:
        recommendations.append(
            "Revenue visibility is limited due to missing order price fields. Capture total_price/current_total_price in webhook payload mapping."
        )

    if top_products:
        top_units = int(top_products[0].get("units") or 0)
        total_top_units = sum(int(product.get("units") or 0) for product in top_products)
        if total_top_units > 0:
            concentration = top_units / total_top_units * 100
            if concentration >= 45:
                recommendations.append(
                    "Sales are concentrated in a single leading product. Test bundles and cross-sell placements to diversify demand."
                )

    if not recommendations:
        recommendations.append(
            "Core sales health looks stable. Next step: track channel-wise conversion and campaign attribution for deeper optimization."
        )

    return recommendations


@login_required
@sales_access_required
def sales_dashboard(request: HttpRequest) -> HttpResponse:
    """Render sales intelligence dashboard from order and order-line data."""
    period = request.GET.get("period", "90d").strip()
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()

    orders_qs = Order.objects.all().order_by("-created_at")
    today = timezone.localdate()

    if period == "7d":
        orders_qs = orders_qs.filter(created_at__date__gte=today - timezone.timedelta(days=7))
    elif period == "30d":
        orders_qs = orders_qs.filter(created_at__date__gte=today - timezone.timedelta(days=30))
    elif period == "365d":
        orders_qs = orders_qs.filter(created_at__date__gte=today - timezone.timedelta(days=365))

    date_from = parse_date(date_from_raw) if date_from_raw else None
    date_to = parse_date(date_to_raw) if date_to_raw else None
    if date_from:
        orders_qs = orders_qs.filter(created_at__date__gte=date_from)
    if date_to:
        orders_qs = orders_qs.filter(created_at__date__lte=date_to)

    orders = list(orders_qs)
    total_orders = len(orders)

    line_qs = OrderLine.objects.filter(order__in=orders_qs)

    insights = _compute_insights(orders, line_qs, total_orders)

    status_breakdown = list(
        orders_qs.values("status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    top_products = list(
        line_qs.exclude(status=OrderLine.STATUS_CANCELLED)
        .values("product_name")
        .annotate(units=Sum("quantity"), orders=Count("order", distinct=True))
        .order_by("-units", "product_name")[:10]
    )

    daily_orders = list(
        orders_qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(order_count=Count("id"))
        .order_by("-day")[:14]
    )
    daily_orders.reverse()

    monthly_orders = list(
        orders_qs.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(order_count=Count("id"))
        .order_by("-month")[:12]
    )
    monthly_orders.reverse()

    recommendations = _build_recommendations(insights, top_products)

    return render(
        request,
        "core/sales/dashboard.html",
        {
            "filters": {
                "period": period,
                "date_from": date_from_raw,
                "date_to": date_to_raw,
            },
            "insights": {
                "total_orders": insights.total_orders,
                "orders_today": insights.orders_today,
                "orders_this_month": insights.orders_this_month,
                "units_sold": insights.units_sold,
                "unique_customers": insights.unique_customers,
                "recurring_customers": insights.recurring_customers,
                "recurring_rate": round(insights.recurring_rate, 1),
                "cancelled_orders": insights.cancelled_orders,
                "cancelled_rate": round(insights.cancelled_rate, 1),
                "return_exchange_orders": insights.return_exchange_orders,
                "return_exchange_rate": round(insights.return_exchange_rate, 1),
                "revenue_rupees": _paise_to_rupees(insights.revenue_paise),
                "aov_rupees": _paise_to_rupees(insights.aov_paise),
                "revenue_coverage_count": insights.revenue_coverage_count,
                "revenue_coverage_rate": round(insights.revenue_coverage_rate, 1),
            },
            "top_products": top_products,
            "status_breakdown": status_breakdown,
            "daily_orders": daily_orders,
            "monthly_orders": monthly_orders,
            "recommendations": recommendations,
        },
    )


@login_required
@finance_access_required
def finance_dashboard(request: HttpRequest) -> HttpResponse:
    """Render Finance module placeholder until feature implementation lands."""
    return render(
        request,
        "core/module_placeholder.html",
        {
            "module_title": "Financial Management",
            "module_description": "Accounting, ledgers, invoicing, and reconciliation workflows will be added here.",
        },
    )
