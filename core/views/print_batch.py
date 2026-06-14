from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from core.models import (
    BlankSKU,
    Design,
    DesignAsset,
    DesignAssetFile,
    Order,
    OrderLine,
    PrintJob,
    PrintJobLine,
    PrintedSKU,
    Vendor,
)
from core.security import inventory_access_required
from core.services import inventory, pdf

SIZE_ORDER = ["S", "M", "L", "XL", "2XL", "3XL"]


def _size_sort_key(size: str) -> tuple[int, str]:
    normalized = (size or "NA").upper()
    if normalized in SIZE_ORDER:
        return (SIZE_ORDER.index(normalized), normalized)
    return (len(SIZE_ORDER), normalized)


def _resolve_line_printed_sku(order_line: OrderLine) -> PrintedSKU:
    if order_line.printed_sku_id is None:
        raise ValueError("Order line has no linked PrintedSKU.")

    requested_size = (order_line.size or "").strip() or None
    base_sku = order_line.printed_sku
    if requested_size == base_sku.size:
        return base_sku

    aligned_sku, _ = PrintedSKU.objects.get_or_create(
        design=base_sku.design,
        variant=base_sku.variant,
        colour=base_sku.colour,
        size=requested_size,
        defaults={
            "on_hand": 0,
            "reserved": 0,
            "buffer_min": base_sku.buffer_min,
            "buffer_target": base_sku.buffer_target,
            "buffer_max": base_sku.buffer_max,
        },
    )
    if order_line.printed_sku_id != aligned_sku.id:
        order_line.printed_sku = aligned_sku
        order_line.save(update_fields=["printed_sku", "updated_at"])
    return aligned_sku


def _resolve_blank_sku(printed_sku: PrintedSKU) -> tuple[BlankSKU | None, int]:
    if printed_sku.blank_sku_id is not None:
        blank_sku = printed_sku.blank_sku
        return blank_sku, blank_sku.available if blank_sku is not None else 0

    asset = printed_sku.design.assets.filter(colour__iexact=printed_sku.colour).first()
    if asset is None:
        asset = printed_sku.design.assets.first()

    blank_fabric = asset.blank_fabric if asset is not None and asset.blank_fabric else "180 GSM"
    blank_sku = BlankSKU.objects.filter(
        fabric__iexact=blank_fabric,
        colour__iexact=printed_sku.colour,
        size__iexact=printed_sku.size or "",
    ).first()
    if blank_sku is None and printed_sku.size is None:
        blank_sku = BlankSKU.objects.filter(
            fabric__iexact=blank_fabric,
            colour__iexact=printed_sku.colour,
        ).first()
    return blank_sku, blank_sku.available if blank_sku is not None else 0


@dataclass(frozen=True)
class SuggestedBatchRow:
    printed_sku: PrintedSKU
    blank_sku: BlankSKU | None
    demand_qty: int
    buffer_top_up_qty: int
    suggested_qty: int
    plain_available: int
    plain_shortfall: int


@dataclass(frozen=True)
class UnmatchedBatchRow:
    product_name: str
    variant: str
    size: str
    demand_qty: int
    order_line_ids: list[str]


def _build_all_batch_rows() -> list[SuggestedBatchRow | UnmatchedBatchRow]:
    candidate_lines = list(
        OrderLine.objects.select_related("printed_sku__design", "order")
        .filter(
            status=OrderLine.STATUS_TO_BE_PRINTED,
            order__status__in=[
                Order.STATUS_NEW,
                Order.STATUS_NEEDS_PRINTING,
                Order.STATUS_IN_PRINTING,
                Order.STATUS_READY_TO_SHIP,
            ],
        )
        .order_by("created_at")
    )

    demand_by_sku: dict[str, int] = {}
    printed_skus: dict[str, PrintedSKU] = {}
    unmatched_demand: dict[tuple[str, str, str], dict[str, object]] = {}

    for line in candidate_lines:
        if line.printed_sku_id is None:
            key = (
                str(line.product_name or "Unknown").strip(),
                str(line.variant or "").strip(),
                str(line.size or "").strip(),
            )
            entry = unmatched_demand.setdefault(key, {"qty": 0, "ids": []})
            entry["qty"] = int(entry["qty"]) + int(line.quantity)
            ids = entry["ids"]
            if isinstance(ids, list):
                ids.append(str(line.id))
        else:
            printed_sku = _resolve_line_printed_sku(line)
            printed_skus[str(printed_sku.id)] = printed_sku
            demand_by_sku[str(printed_sku.id)] = demand_by_sku.get(str(printed_sku.id), 0) + int(line.quantity)

    rows: list[SuggestedBatchRow | UnmatchedBatchRow] = []
    for printed_sku_id, demand_qty in demand_by_sku.items():
        printed_sku = printed_skus[printed_sku_id]
        buffer_top_up_qty = max(printed_sku.buffer_target - printed_sku.available, 0)
        suggested_qty = demand_qty + buffer_top_up_qty
        blank_sku, plain_available = _resolve_blank_sku(printed_sku)
        plain_shortfall = max(suggested_qty - plain_available, 0)
        rows.append(
            SuggestedBatchRow(
                printed_sku=printed_sku,
                blank_sku=blank_sku,
                demand_qty=demand_qty,
                buffer_top_up_qty=buffer_top_up_qty,
                suggested_qty=suggested_qty,
                plain_available=plain_available,
                plain_shortfall=plain_shortfall,
            )
        )

    for (product_name, variant, size), entry in unmatched_demand.items():
        ids = entry.get("ids", [])
        rows.append(
            UnmatchedBatchRow(
                product_name=product_name,
                variant=variant,
                size=size,
                demand_qty=int(entry.get("qty", 0)),
                order_line_ids=[str(x) for x in ids] if isinstance(ids, list) else [],
            )
        )

    matched = sorted(
        [r for r in rows if isinstance(r, SuggestedBatchRow)],
        key=lambda row: (row.printed_sku.design.name, row.printed_sku.colour, row.printed_sku.size or ""),
    )
    unmatched = sorted(
        [r for r in rows if isinstance(r, UnmatchedBatchRow)],
        key=lambda row: (row.product_name, row.variant, row.size),
    )
    return matched + unmatched


def _build_suggested_rows() -> list[SuggestedBatchRow]:
    return [r for r in _build_all_batch_rows() if isinstance(r, SuggestedBatchRow)]


def _build_unmatched_rows() -> list[UnmatchedBatchRow]:
    return [r for r in _build_all_batch_rows() if isinstance(r, UnmatchedBatchRow)]


def _link_blank_sku_batch(request: HttpRequest) -> HttpResponse:
    design_name = request.POST.get("design_name", "").strip()
    colour = request.POST.get("colour", "").strip()
    plain_option = request.POST.get("plain_option", "").strip()

    design = Design.objects.filter(name=design_name).first()
    if design is None:
        return JsonResponse({"ok": False, "detail": f"Design '{design_name}' not found."}, status=404)

    design_asset, _ = DesignAsset.objects.get_or_create(design=design, colour=colour)

    if plain_option:
        try:
            selected_fabric, selected_colour = [part.strip() for part in plain_option.split("|||", 1)]
        except ValueError:
            return JsonResponse({"ok": False, "detail": "Invalid plain SKU selection."}, status=400)

        if not BlankSKU.objects.filter(fabric=selected_fabric, colour=selected_colour).exists():
            return JsonResponse({"ok": False, "detail": "Selected plain SKU group not found."}, status=404)

        design_asset.blank_fabric = selected_fabric
        design_asset.blank_sku = None
        design_asset.save(update_fields=["blank_fabric", "blank_sku", "updated_at"])
    else:
        design_asset.blank_sku = None
        design_asset.save(update_fields=["blank_sku", "updated_at"])

    PrintedSKU.objects.filter(design=design, colour=colour).update(
        design_asset=design_asset,
        blank_sku=None,
    )

    label = plain_option.replace("|||", " / ") if plain_option else "Unlinked"
    return JsonResponse({"ok": True, "message": label})


def _link_mockup_batch(request: HttpRequest) -> HttpResponse:
    design_name = request.POST.get("design_name", "").strip()
    colour = request.POST.get("colour", "").strip()
    file_url = request.POST.get("file_url", "").strip()
    placement = request.POST.get("placement", "front").strip().lower()

    if placement not in {"front", "back", "sleeve", "full"}:
        placement = "front"

    design = Design.objects.filter(name=design_name).first()
    if design is None:
        return JsonResponse({"ok": False, "detail": "Design not found."}, status=404)
    if not file_url:
        return JsonResponse({"ok": False, "detail": "File URL required."}, status=400)

    design_asset, _ = DesignAsset.objects.get_or_create(design=design, colour=colour)
    file_obj, _ = DesignAssetFile.objects.update_or_create(
        design_asset=design_asset,
        file_type=DesignAssetFile.FileType.MOCKUP,
        placement=placement,
        defaults={"file_url": file_url},
    )
    return JsonResponse({"ok": True, "message": f"Mockup linked: {placement}", "file_id": str(file_obj.id)})


def _mark_allocated_lines_in_printing(printed_sku: PrintedSKU, qty_to_allocate: int) -> set[str]:
    touched_order_ids: set[str] = set()
    remaining = qty_to_allocate
    candidate_lines = (
        OrderLine.objects.select_for_update()
        .select_related("order")
        .filter(
            printed_sku=printed_sku,
            status=OrderLine.STATUS_TO_BE_PRINTED,
            order__status__in=[
                Order.STATUS_NEW,
                Order.STATUS_NEEDS_PRINTING,
                Order.STATUS_READY_TO_SHIP,
                Order.STATUS_IN_PRINTING,
            ],
        )
        .order_by("created_at")
    )
    for line in candidate_lines:
        if remaining <= 0:
            break
        line.status = OrderLine.STATUS_IN_PRINTING
        line.save(update_fields=["status", "updated_at"])
        touched_order_ids.add(str(line.order_id))
        remaining -= int(line.quantity)
    return touched_order_ids


@login_required
@inventory_access_required
def pick_list(request: HttpRequest, job_id: str) -> HttpResponse:
    print_job = get_object_or_404(
        PrintJob.objects.select_related("vendor").prefetch_related("lines__printed_sku__design__assets", "lines__blank_sku"),
        id=job_id,
    )
    rows = []
    for line in print_job.lines.order_by("blank_sku__fabric", "blank_sku__colour", "blank_sku__size"):
        rows.append({"blank_sku": line.blank_sku, "printed_sku": line.printed_sku, "qty_sent": line.qty_sent})
    total = sum(r["qty_sent"] for r in rows)
    return render(request, "pick_list.html", {"print_job": print_job, "rows": rows, "total": total})


@login_required
@inventory_access_required
def print_pack_file(request: HttpRequest, filename: str) -> HttpResponse:
    """Serve generated print pack PDFs in production for authenticated internal users."""
    media_root = Path(getattr(settings, "MEDIA_ROOT", "media"))
    base_dir = (media_root / "print_packs").resolve()
    file_path = (base_dir / filename).resolve()

    if not str(file_path).startswith(str(base_dir)):
        raise Http404("Invalid file path")

    if not file_path.exists() or not file_path.is_file():
        # Railway deployments can lose local media files. Regenerate on-demand
        # when filename follows print_pack_<print_job_uuid>.pdf naming.
        match = re.fullmatch(r"print_pack_([0-9a-fA-F-]{36})\.pdf", filename)
        if match:
            job_id = match.group(1)
            try:
                pdf.build_print_pack_pdf(job_id)
            except Exception:
                raise Http404("Print pack file could not be regenerated")

        if not file_path.exists() or not file_path.is_file():
            raise Http404("Print pack file not found")

    response = FileResponse(file_path.open("rb"), content_type="application/pdf")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@login_required
@inventory_access_required
def suggest_batch(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "link_blank_sku":
            return _link_blank_sku_batch(request)
        if action == "link_mockup":
            return _link_mockup_batch(request)

    rows = _build_suggested_rows()
    unmatched_rows = _build_unmatched_rows()
    vendors = Vendor.objects.filter(is_active=True).order_by("name")

    recent_jobs = (
        PrintJob.objects.select_related("vendor").prefetch_related("lines").order_by("-created_at")[:20]
    )
    recent_job_rows: list[dict[str, object]] = []
    for job in recent_jobs:
        total_units = sum(line.qty_sent for line in job.lines.all())
        recent_job_rows.append(
            {
                "id": str(job.id),
                "vendor_name": job.vendor.name,
                "status": job.status,
                "sent_at": job.sent_at,
                "total_units": total_units,
                "pdf_url": job.pdf_url,
            }
        )

    grouped_rows: dict[tuple[str, str, str], dict[str, object]] = {}
    sizes_seen: set[str] = set()
    for row in rows:
        size_label = row.printed_sku.size or "NA"
        sizes_seen.add(size_label)
        key = (row.printed_sku.design.name, row.printed_sku.variant or "BASE", row.printed_sku.colour)
        group = grouped_rows.setdefault(
            key,
            {
                "design_name": row.printed_sku.design.name,
                "variant": row.printed_sku.variant or "BASE",
                "colour": row.printed_sku.colour,
                "linked_plain_option": "",
                "design_asset_mockup_files": [],
                "size_rows": {},
            },
        )

        if not group["linked_plain_option"] and row.printed_sku.design_asset:
            if row.printed_sku.design_asset.blank_sku_id:
                group["linked_plain_option"] = (
                    f"{row.printed_sku.design_asset.blank_sku.fabric}|||{row.printed_sku.design_asset.blank_sku.colour}"
                )
            elif row.printed_sku.design_asset.blank_fabric:
                group["linked_plain_option"] = f"{row.printed_sku.design_asset.blank_fabric}|||{row.printed_sku.colour}"
            group["design_asset_mockup_files"] = list(
                row.printed_sku.design_asset.files.filter(file_type=DesignAssetFile.FileType.MOCKUP).values("id", "placement", "file_url")
            )

        size_rows = group["size_rows"]
        if isinstance(size_rows, dict):
            size_rows[size_label] = row

    ordered_sizes = sorted(sizes_seen, key=_size_sort_key)
    grouped_batch_rows: list[dict[str, object]] = []
    missing_size_groups: list[dict[str, object]] = []
    for group in grouped_rows.values():
        size_rows = group["size_rows"]
        group["size_cells"] = [size_rows.get(size) if isinstance(size_rows, dict) else None for size in ordered_sizes]
        missing_cell = (size_rows.get("NA") if isinstance(size_rows, dict) else None)
        if missing_cell is not None:
            missing_size_groups.append(
                {
                    "design_name": group["design_name"],
                    "variant": group["variant"],
                    "colour": group["colour"],
                    "qty": missing_cell.suggested_qty,
                }
            )
        grouped_batch_rows.append(group)

    grouped_batch_rows.sort(key=lambda row: (str(row["design_name"]), str(row["variant"]), str(row["colour"])))

    all_blank_skus = list(
        BlankSKU.objects.order_by("fabric", "colour").values("fabric", "colour").distinct()
    )

    return render(
        request,
        "print_batch.html",
        {
            "rows": rows,
            "vendors": vendors,
            "sizes": ordered_sizes,
            "grouped_rows": grouped_batch_rows,
            "missing_size_groups": missing_size_groups,
            "has_missing_sizes": bool(missing_size_groups),
            "recent_jobs": recent_job_rows,
            "unmatched_rows": unmatched_rows,
            "all_blank_skus": all_blank_skus,
        },
    )


@login_required
@inventory_access_required
@require_POST
def confirm_batch(request: HttpRequest) -> HttpResponse:
    vendor_id = request.POST.get("vendor_id", "")
    if not vendor_id:
        messages.error(request, "Select a vendor before confirming the print batch.")
        return redirect("print-batch-suggest")

    try:
        vendor = Vendor.objects.get(id=vendor_id, is_active=True)
    except Vendor.DoesNotExist:
        messages.error(request, "Selected vendor was not found or is inactive.")
        return redirect("print-batch-suggest")

    rows = _build_suggested_rows()
    row_lookup = {str(row.printed_sku.id): row for row in rows}
    selected: list[tuple[SuggestedBatchRow, int]] = []

    for printed_sku_id, row in row_lookup.items():
        field_name = f"qty_{printed_sku_id}"
        if field_name not in request.POST:
            continue
        qty = int(request.POST.get(field_name, row.suggested_qty) or 0)
        if qty <= 0:
            continue
        if row.blank_sku is None:
            messages.error(request, f"No matching blank SKU found for {row.printed_sku}.")
            return redirect("print-batch-suggest")
        if qty > row.plain_available:
            messages.error(
                request,
                f"Insufficient plain stock for {row.blank_sku}. Requested {qty}, available {row.plain_available}.",
            )
            return redirect("print-batch-suggest")
        selected.append((row, qty))

    if not selected:
        messages.error(request, "No batch lines were selected for confirmation.")
        return redirect("print-batch-suggest")

    with transaction.atomic():
        print_job = PrintJob.objects.create(
            vendor=vendor,
            status=PrintJob.STATUS_SENT,
            sent_at=timezone.now(),
            notes=request.POST.get("notes", ""),
        )
        touched_order_ids: set[str] = set()
        for row, qty in selected:
            inventory.deduct_plain(str(row.blank_sku.id), qty, actor=request.user)
            PrintJobLine.objects.create(
                print_job=print_job,
                printed_sku=row.printed_sku,
                blank_sku=row.blank_sku,
                qty_sent=qty,
            )
            touched_order_ids.update(_mark_allocated_lines_in_printing(row.printed_sku, qty))

        if touched_order_ids:
            Order.objects.select_for_update().filter(id__in=touched_order_ids).update(status=Order.STATUS_IN_PRINTING)

    pdf_url = pdf.build_print_pack_pdf(str(print_job.id))
    messages.success(
        request,
        format_html(
            'Print job {} created. <a href="{}" target="_blank" rel="noopener">Print Pack</a> &nbsp;|&nbsp; '
            '<a href="{}" target="_blank" rel="noopener">Pick List</a>',
            print_job.id,
            pdf_url,
            reverse("pick-list", args=[print_job.id]),
        ),
    )
    return redirect("print-batch-suggest")


print_batch_list_view = suggest_batch
generate_print_batch_view = suggest_batch
confirm_print_batch_view = confirm_batch
