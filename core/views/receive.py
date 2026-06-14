from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Order, OrderLine, PrintBatch, PrintJob, PrintJobLine, ReprintTask
from core.security import inventory_access_required
from core.services.inventory import receive_print_job_line

SIZE_ORDER = ["S", "M", "L", "XL", "2XL", "3XL"]


def _size_sort_key(size: str) -> tuple[int, str]:
    normalized = (size or "NA").upper()
    if normalized in SIZE_ORDER:
        return (SIZE_ORDER.index(normalized), normalized)
    return (len(SIZE_ORDER), normalized)


@login_required
@inventory_access_required
def receive_dashboard_view(request: HttpRequest) -> HttpResponse:
    """Render mobile-friendly receive queue — shows all sent and partially-received jobs."""
    jobs = (
        PrintJob.objects.select_related("batch", "vendor")
        .prefetch_related("lines__printed_sku__design", "lines__blank_sku")
        .filter(status__in=[PrintJob.STATUS_SENT, PrintJob.STATUS_PARTIALLY_RECEIVED])
        .order_by("-created_at")
    )
    job_cards: list[dict[str, object]] = []
    for job in jobs:
        grouped_rows: dict[tuple[str, str, str], dict[str, object]] = {}
        sizes_seen: set[str] = set()
        for line in job.lines.all():
            size_label = line.printed_sku.size or "NA"
            sizes_seen.add(size_label)
            key = (
                line.printed_sku.design.name,
                line.printed_sku.variant or "BASE",
                line.printed_sku.colour,
            )
            row = grouped_rows.setdefault(
                key,
                {
                    "design_name": line.printed_sku.design.name,
                    "variant": line.printed_sku.variant or "BASE",
                    "colour": line.printed_sku.colour,
                    "size_lines": {},
                    "blank_summary": [],
                },
            )
            size_lines = row["size_lines"]
            if isinstance(size_lines, dict):
                size_lines[size_label] = line
            if line.blank_sku is not None:
                blank_summary = row["blank_summary"]
                blank_label = f"{line.blank_sku.fabric} / {line.blank_sku.colour}"
                if isinstance(blank_summary, list) and blank_label not in blank_summary:
                    blank_summary.append(blank_label)

        ordered_sizes = sorted(sizes_seen, key=_size_sort_key)
        grouped_list: list[dict[str, object]] = []
        for row in grouped_rows.values():
            size_lines = row["size_lines"]
            row["size_cells"] = [size_lines.get(size) if isinstance(size_lines, dict) else None for size in ordered_sizes]
            grouped_list.append(row)
        grouped_list.sort(key=lambda row: (str(row["design_name"]), str(row["variant"]), str(row["colour"])))
        job_cards.append({"job": job, "sizes": ordered_sizes, "rows": grouped_list})
    return render(request, "core/receive_dashboard.html", {"job_cards": job_cards})


@login_required
@inventory_access_required
@require_POST
def receive_line_view(request: HttpRequest, line_id: str) -> HttpResponse:
    """Receive a single print job line; auto-flip orders to Ready-to-Ship when complete."""
    line = get_object_or_404(
        PrintJobLine.objects.select_related("print_job__batch", "printed_sku"),
        id=line_id,
    )
    try:
        qty_defective = int(request.POST.get("qty_defective", 0))
    except ValueError:
        messages.error(request, "Defective quantity must be an integer.")
        return redirect("receive-dashboard")

    if qty_defective < 0 or qty_defective > line.qty_sent:
        messages.error(request, "Defective quantity must be between 0 and qty sent.")
        return redirect("receive-dashboard")

    # Automatically compute qty_good as remainder
    qty_good = line.qty_sent - qty_defective
    notes = request.POST.get("notes", "").strip()

    try:
        receive_print_job_line(
            str(line.id),
            qty_good=qty_good,
            qty_defective=qty_defective,
            actor=request.user,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("receive-dashboard")

    # Log notes if provided
    if notes:
        line.print_job.notes = (line.print_job.notes or "") + f"\n[{line.printed_sku}] {notes}"
        line.print_job.save(update_fields=["notes", "updated_at"])

    # Create reprint task if shortfall
    shortfall = qty_defective
    if shortfall > 0:
        ReprintTask.objects.get_or_create(
            source=line,
            printed_sku=line.printed_sku,
            defaults={"qty": shortfall, "status": "pending"},
        )
        messages.warning(
            request,
            f"Shortfall of {shortfall} units for {line.printed_sku} — reprint task created.",
        )

    # Check if entire job is fully received
    all_lines = list(line.print_job.lines.all())
    job_complete = all(
        ln.qty_received_good + ln.qty_received_defective >= ln.qty_sent
        for ln in all_lines
    )

    if job_complete:
        with transaction.atomic():
            line.print_job.status = PrintJob.STATUS_RECEIVED
            line.print_job.save(update_fields=["status", "updated_at"])
            if line.print_job.batch:
                line.print_job.batch.status = PrintBatch.STATUS_RECEIVED
                line.print_job.batch.save(update_fields=["status", "updated_at"])

        # Flip any IN_PRINTING orders whose ALL lines are now received/ready
        _flip_ready_orders(line.printed_sku.id)
        messages.success(request, f"Job fully received. Orders updated to Ready to Ship.")
    else:
        with transaction.atomic():
            line.print_job.status = PrintJob.STATUS_PARTIALLY_RECEIVED
            line.print_job.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Line received — {qty_good} good, {qty_defective} defective.")

    return redirect("receive-dashboard")


@login_required
@inventory_access_required
@require_POST
def receive_job_all_good_view(request: HttpRequest, job_id: str) -> HttpResponse:
    """Bulk receive an entire print job — mark all lines as received with full qty as good."""
    job = get_object_or_404(PrintJob, id=job_id)

    try:
        with transaction.atomic():
            for line in job.lines.all():
                receive_print_job_line(
                    str(line.id),
                    qty_good=line.qty_sent,
                    qty_defective=0,
                    actor=request.user,  # type: ignore[arg-type]
                )
            # Mark job as received
            job.status = PrintJob.STATUS_RECEIVED
            job.save(update_fields=["status", "updated_at"])
            if job.batch:
                job.batch.status = PrintBatch.STATUS_RECEIVED
                job.batch.save(update_fields=["status", "updated_at"])
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("receive-dashboard")

    # Flip orders
    for line in job.lines.all():
        _flip_ready_orders(line.printed_sku_id)

    messages.success(request, f"Batch received — all {job.lines.count()} lines marked as good.")
    return redirect("receive-dashboard")


def _flip_ready_orders(printed_sku_id: object) -> None:
    """Flip orders to Ready-to-Ship when all their IN_PRINTING lines are now received."""
    candidate_orders = Order.objects.filter(
        status=Order.STATUS_IN_PRINTING,
        lines__printed_sku_id=printed_sku_id,
    ).distinct()

    for order in candidate_orders:
        lines = list(order.lines.exclude(status=OrderLine.STATUS_CANCELLED))
        if not lines:
            continue
        all_ready = all(
            ln.status in {OrderLine.STATUS_READY_SHIP, OrderLine.STATUS_SHIPPED}
            or ln.printed_sku_id is None
            for ln in lines
        )
        # Also flip if lines are IN_PRINTING but their print job is received
        all_received = all(
            _line_stock_received(ln) for ln in lines
        )
        if all_ready or all_received:
            with transaction.atomic():
                order.status = Order.STATUS_READY_TO_SHIP
                order.save(update_fields=["status", "updated_at"])
                order.lines.filter(
                    status=OrderLine.STATUS_IN_PRINTING
                ).update(status=OrderLine.STATUS_READY_SHIP)


def _line_stock_received(line: OrderLine) -> bool:
    """Return True if this line's printed stock has been received by any print job."""
    if line.status in {OrderLine.STATUS_READY_SHIP, OrderLine.STATUS_SHIPPED}:
        return True
    if line.printed_sku_id is None:
        return True
    return PrintJobLine.objects.filter(
        printed_sku_id=line.printed_sku_id,
        print_job__status__in=[PrintJob.STATUS_RECEIVED, PrintJob.STATUS_CLOSED],
        qty_received_good__gte=line.quantity,
    ).exists()
