"""Manual inventory adjustment view."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from core.models import BlankSKU, PrintedSKU, StockMovement
from core.security import inventory_access_required
from core.services.inventory import manual_adjust


@login_required
@inventory_access_required
def adjust_inventory(request: HttpRequest) -> HttpResponse:
    """Manual stock adjustment with reason logging — plain or printed pool."""
    blank_skus = BlankSKU.objects.order_by("fabric", "colour", "size")
    printed_skus = PrintedSKU.objects.select_related("design").order_by(
        "design__name", "variant", "colour", "size"
    )
    reasons = StockMovement.Reason.choices

    if request.method == "POST":
        pool = request.POST.get("pool", "").strip()
        sku_id = request.POST.get("sku_id", "").strip()
        delta_raw = request.POST.get("delta", "").strip()
        reason = request.POST.get("reason", "").strip()
        note = request.POST.get("note", "").strip()

        if not pool or not sku_id or not delta_raw or not reason:
            messages.error(request, "Pool, SKU, delta, and reason are all required.")
        else:
            try:
                delta = int(delta_raw)
                manual_adjust(
                    pool=pool,
                    sku_id=sku_id,
                    delta=delta,
                    reason=reason,
                    note=note,
                    actor=request.user,  # type: ignore[arg-type]
                )
                messages.success(
                    request,
                    f"Adjustment of {delta:+d} applied successfully.",
                )
                return redirect("adjust-inventory")
            except (ValueError, LookupError) as exc:
                messages.error(request, str(exc))

    return render(
        request,
        "core/adjust.html",
        {
            "blank_skus": blank_skus,
            "printed_skus": printed_skus,
            "reasons": reasons,
        },
    )
