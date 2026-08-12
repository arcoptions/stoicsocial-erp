from __future__ import annotations

import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from core.models import BlankSKU, Design, DesignAsset, Order, OrderLine, PrintedSKU


MASTER_DATA_FILES: tuple[tuple[str, str, bool], ...] = (
    ("designs", "Designs & Assets", True),
    ("blank_skus", "Plain SKUs & Opening Stock", True),
    ("printed_skus", "Printed SKUs & Opening Stock", True),
    ("vendors", "Print Vendors", False),
)
MAX_MASTER_DATA_FILE_SIZE = 5 * 1024 * 1024


def _require_superuser(request: HttpRequest) -> None:
    """Reject master-data operations unless the authenticated user is a superuser."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied


@login_required
@require_http_methods(["GET", "POST"])
def import_master_data(request: HttpRequest) -> HttpResponse:
    """Validate or import a production master-data CSV bundle from the UI."""
    _require_superuser(request)

    if request.method == "POST":
        dry_run = request.POST.get("dry_run") == "on"
        if not dry_run and request.POST.get("confirm_import") != "on":
            messages.error(request, "Confirm that this import may update existing master data and stock values.")
            return redirect("import-master-data")

        uploaded_files = {}
        for field_name, label, required in MASTER_DATA_FILES:
            uploaded_file = request.FILES.get(field_name)
            if required and uploaded_file is None:
                messages.error(request, f"{label} CSV is required.")
                return redirect("import-master-data")
            if uploaded_file is None:
                continue
            if not uploaded_file.name.lower().endswith(".csv"):
                messages.error(request, f"{label} must be a CSV file.")
                return redirect("import-master-data")
            if uploaded_file.size > MAX_MASTER_DATA_FILE_SIZE:
                messages.error(request, f"{label} exceeds the 5 MB upload limit.")
                return redirect("import-master-data")
            uploaded_files[field_name] = uploaded_file

        try:
            with TemporaryDirectory() as directory:
                bundle_dir = Path(directory)
                for field_name, uploaded_file in uploaded_files.items():
                    destination = bundle_dir / f"{field_name}.csv"
                    with destination.open("wb") as handle:
                        for chunk in uploaded_file.chunks():
                            handle.write(chunk)

                output = io.StringIO()
                call_command(
                    "import_production_csv_bundle",
                    "--dir",
                    str(bundle_dir),
                    *(('--dry-run',) if dry_run else ()),
                    stdout=output,
                )
        except (CommandError, UnicodeError, ValueError) as exc:
            messages.error(request, f"Master data import failed: {exc}")
        else:
            action = "validated" if dry_run else "imported"
            messages.success(request, f"Master data {action} successfully.")

        return redirect("import-master-data")

    return render(request, "core/import_master_data.html", {"master_data_files": MASTER_DATA_FILES})


@login_required
def download_master_data_templates(request: HttpRequest) -> FileResponse:
    """Download the production master-data CSV template bundle."""
    _require_superuser(request)
    template_path = Path(__file__).resolve().parents[2] / "docs" / "templates" / "BoldERP_New_Data_Templates.zip"
    return FileResponse(
        template_path.open("rb"),
        as_attachment=True,
        filename="BoldERP_New_Data_Templates.zip",
    )


@login_required
@require_http_methods(["GET", "POST"])
def import_test_data(request: HttpRequest) -> HttpResponse:
    """Unified test data import interface for testers."""
    if request.method == "POST":
        import_type = request.POST.get("import_type", "").strip()
        file_obj = request.FILES.get("csv_file")

        if not import_type:
            messages.error(request, "Please select an import type.")
            return redirect("import-test-data")

        if not file_obj:
            messages.error(request, "Please select a CSV file to upload.")
            return redirect("import-test-data")

        try:
            result = _handle_import(import_type, file_obj)
            if result["success"]:
                messages.success(request, result["message"])
            else:
                messages.error(request, result["message"])
        except Exception as exc:
            messages.error(request, f"Import error: {str(exc)}")

        return redirect("import-test-data")

    return render(
        request,
        "core/import_test_data.html",
        {
            "import_types": [
                ("designs", "Designs & Assets"),
                ("blank_skus", "Blank SKUs (Inventory)"),
                ("printed_skus", "Printed SKUs"),
                ("orders", "Orders & Lines"),
            ],
        },
    )


@login_required
def download_csv_template(request: HttpRequest, template_name: str) -> HttpResponse:
    """Serve CSV template files for testers to download and fill in."""
    templates = {
        "designs": _generate_designs_template(),
        "blank_skus": _generate_blank_skus_template(),
        "printed_skus": _generate_printed_skus_template(),
        "orders": _generate_orders_template(),
    }

    if template_name not in templates:
        messages.error(request, "Template not found.")
        return redirect("import-test-data")

    csv_content = templates[template_name]
    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{template_name}_template.csv"'
    return response


def _handle_import(import_type: str, file_obj) -> dict[str, str | bool]:
    """Dispatch import based on type."""
    content = file_obj.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    if not rows:
        return {"success": False, "message": "CSV file is empty."}

    if import_type == "designs":
        return _import_designs(rows)
    elif import_type == "blank_skus":
        return _import_blank_skus(rows)
    elif import_type == "printed_skus":
        return _import_printed_skus(rows)
    elif import_type == "orders":
        return _import_orders(rows)
    else:
        return {"success": False, "message": "Unknown import type."}


def _import_designs(rows: list[dict[str, str]]) -> dict[str, str | bool]:
    """Import designs and design assets."""
    created = 0
    for row in rows:
        design_name = (row.get("design_name") or "").strip()
        if not design_name:
            continue

        colour = (row.get("colour") or "").strip() or "Black"
        design, _ = Design.objects.get_or_create(
            name=design_name,
            defaults={
                "product_type": row.get("product_type") or Design.ProductType.TSHIRT,
                "sub_category": row.get("sub_category") or Design.SubCategory.REGULAR,
                "material": row.get("material") or "Cotton",
                "fit": row.get("fit") or Design.Fit.REGULAR,
                "has_variants": False,
                "variants": [],
            },
        )

        DesignAsset.objects.update_or_create(
            design=design,
            colour=colour,
            defaults={
                "colour_hex": (row.get("colour_hex") or "").strip() or "#1b1b1b",
                "artwork_url": (row.get("artwork_url") or "").strip() or "https://example.com/artwork.png",
                "mockup_url": (row.get("mockup_url") or "").strip() or "https://example.com/mockup.png",
                "blank_fabric": (row.get("blank_fabric") or "").strip() or "180 GSM",
                "print_areas": (row.get("print_areas") or "").strip() or "Front",
                "placement_note": (row.get("placement_note") or "").strip() or "",
            },
        )
        created += 1

    return {"success": True, "message": f"Imported {created} design(s) with assets."}


def _import_blank_skus(rows: list[dict[str, str]]) -> dict[str, str | bool]:
    """Import blank SKU inventory."""
    created = 0
    for row in rows:
        fabric = (row.get("fabric") or "").strip()
        colour = (row.get("colour") or "").strip()
        size = (row.get("size") or "").strip().upper()

        if not all([fabric, colour, size]):
            continue

        on_hand = int(float((row.get("on_hand") or "0").strip())) if (row.get("on_hand") or "").strip() else 0
        BlankSKU.objects.update_or_create(
            fabric=fabric,
            colour=colour,
            size=size,
            defaults={
                "on_hand": on_hand,
                "reserved": int(float((row.get("reserved") or "0").strip())) if (row.get("reserved") or "").strip() else 0,
                "reorder_min": int(float((row.get("reorder_min") or "0").strip())) if (row.get("reorder_min") or "").strip() else 0,
                "reorder_target": int(float((row.get("reorder_target") or "0").strip())) if (row.get("reorder_target") or "").strip() else 0,
            },
        )
        created += 1

    return {"success": True, "message": f"Imported {created} blank SKU rows."}


def _import_printed_skus(rows: list[dict[str, str]]) -> dict[str, str | bool]:
    """Import printed SKU records."""
    created = 0
    for row in rows:
        design_name = (row.get("design_name") or "").strip()
        colour = (row.get("colour") or "").strip()
        size = (row.get("size") or "").strip().upper()

        if not all([design_name, colour, size]):
            continue

        design = Design.objects.filter(name__iexact=design_name).first()
        if not design:
            design = Design.objects.create(
                name=design_name,
                product_type=Design.ProductType.TSHIRT,
                sub_category=Design.SubCategory.REGULAR,
            )

        design_asset = DesignAsset.objects.filter(design=design, colour__iexact=colour).first()
        blank_sku = None
        if design_asset:
            blank_sku = BlankSKU.objects.filter(
                fabric__iexact=design_asset.blank_fabric,
                colour__iexact=colour,
                size__iexact=size,
            ).first()

        variant = (row.get("variant") or "").strip() or None
        on_hand = int(float((row.get("on_hand") or "0").strip())) if (row.get("on_hand") or "").strip() else 0
        PrintedSKU.objects.update_or_create(
            design=design,
            variant=variant,
            colour=colour,
            size=size,
            defaults={
                "design_asset": design_asset,
                "blank_sku": blank_sku,
                "on_hand": on_hand,
                "reserved": int(float((row.get("reserved") or "0").strip())) if (row.get("reserved") or "").strip() else 0,
                "is_active": True,
                "buffer_min": int(float((row.get("buffer_min") or "0").strip())) if (row.get("buffer_min") or "").strip() else 0,
                "buffer_target": int(float((row.get("buffer_target") or "0").strip())) if (row.get("buffer_target") or "").strip() else 0,
                "buffer_max": int(float((row.get("buffer_max") or "0").strip())) if (row.get("buffer_max") or "").strip() else 0,
                "is_test_data": True,
            },
        )
        created += 1

    return {"success": True, "message": f"Imported {created} printed SKU rows."}


def _import_orders(rows: list[dict[str, str]]) -> dict[str, str | bool]:
    """Import test orders and order lines."""
    created_orders = 0
    created_lines = 0

    for row in rows:
        shopify_order_id = (row.get("shopify_order_id") or "").strip()
        if not shopify_order_id:
            continue

        order, created = Order.objects.get_or_create(
            shopify_order_id=shopify_order_id,
            defaults={
                "order_no": (row.get("order_no") or "").strip() or shopify_order_id,
                "customer_name": (row.get("customer_name") or "").strip() or "Test Customer",
                "email": (row.get("email") or "").strip() or "test@example.com",
                "tags": [tag.strip() for tag in ((row.get("tags") or "").split(",") if row.get("tags") else [])],
                "status": row.get("status") or Order.STATUS_NEEDS_PRINTING,
                "shopify_fulfillment_status": (row.get("fulfillment_status") or "").strip() or "unfulfilled",
                "shopify_delivery_status": (row.get("delivery_status") or "").strip() or "pending",
                "raw_payload": {"source": "ui_test_import"},
                "is_test_data": True,
            },
        )
        if created:
            created_orders += 1

        product_name = (row.get("product_name") or "").strip()
        if product_name:
            design = Design.objects.filter(name__iexact=product_name).first()
            colour = (row.get("colour") or "").strip()
            size = (row.get("size") or "").strip().upper()
            variant = (row.get("variant") or "").strip() or None

            printed_sku = None
            if design and colour and size:
                printed_sku = PrintedSKU.objects.filter(
                    design=design,
                    variant=variant,
                    colour__iexact=colour,
                    size__iexact=size,
                ).first()

            quantity = int(float((row.get("quantity") or "1").strip())) if (row.get("quantity") or "").strip() else 1
            line_status = row.get("line_status") or OrderLine.STATUS_TO_BE_PRINTED
            shopify_line_id = (row.get("shopify_line_id") or "").strip() or f"{shopify_order_id}-line-{created_lines}"

            OrderLine.objects.update_or_create(
                shopify_line_id=shopify_line_id,
                defaults={
                    "order": order,
                    "product_name": product_name,
                    "variant": variant or "",
                    "size": size,
                    "quantity": quantity,
                    "printed_sku": printed_sku,
                    "is_bundle": False,
                    "bundle_components": [],
                    "status": line_status,
                },
            )
            created_lines += 1

    return {"success": True, "message": f"Imported {created_orders} order(s) and {created_lines} order line(s)."}


def _generate_designs_template() -> str:
    """Generate CSV template for designs."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "design_name",
        "product_type",
        "sub_category",
        "material",
        "fit",
        "colour",
        "colour_hex",
        "blank_fabric",
        "artwork_url",
        "mockup_url",
        "print_areas",
        "placement_note",
    ])
    writer.writerow([
        "My First Design",
        "Tshirt",
        "Regular",
        "Cotton",
        "Regular",
        "Black",
        "#1b1b1b",
        "180 GSM",
        "https://example.com/art.png",
        "https://example.com/mockup.png",
        "Front",
        "Center chest placement",
    ])
    return output.getvalue()


def _generate_blank_skus_template() -> str:
    """Generate CSV template for blank SKUs."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["fabric", "colour", "size", "on_hand", "reserved", "reorder_min", "reorder_target"])
    writer.writerow(["180 GSM", "Black", "M", "100", "0", "10", "50"])
    writer.writerow(["180 GSM", "Black", "L", "80", "0", "10", "50"])
    writer.writerow(["180 GSM", "White", "M", "60", "0", "10", "40"])
    return output.getvalue()


def _generate_printed_skus_template() -> str:
    """Generate CSV template for printed SKUs."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "design_name",
        "variant",
        "colour",
        "size",
        "on_hand",
        "reserved",
        "buffer_min",
        "buffer_target",
        "buffer_max",
        "blank_fabric",
    ])
    writer.writerow([
        "My First Design",
        "",
        "Black",
        "M",
        "0",
        "0",
        "3",
        "12",
        "30",
        "180 GSM",
    ])
    writer.writerow([
        "My First Design",
        "",
        "Black",
        "L",
        "0",
        "0",
        "3",
        "12",
        "30",
        "180 GSM",
    ])
    return output.getvalue()


def _generate_orders_template() -> str:
    """Generate CSV template for orders."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "shopify_order_id",
        "order_no",
        "customer_name",
        "email",
        "shopify_line_id",
        "product_name",
        "variant",
        "colour",
        "size",
        "quantity",
        "status",
        "line_status",
        "fulfillment_status",
        "delivery_status",
        "tags",
    ])
    writer.writerow([
        "TEST-001",
        "#001",
        "John Doe",
        "john@example.com",
        "TEST-001-L1",
        "My First Design",
        "",
        "Black",
        "M",
        "2",
        "needs_printing",
        "to_be_printed",
        "unfulfilled",
        "pending",
        "test,demo",
    ])
    writer.writerow([
        "TEST-002",
        "#002",
        "Jane Smith",
        "jane@example.com",
        "TEST-002-L1",
        "My First Design",
        "",
        "Black",
        "L",
        "1",
        "in_printing",
        "in_printing",
        "unfulfilled",
        "in_transit",
        "test,priority",
    ])
    return output.getvalue()
