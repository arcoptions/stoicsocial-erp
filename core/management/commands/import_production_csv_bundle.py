from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import BlankSKU, Design, DesignAsset, Order, OrderLine, PrintedSKU


ORDER_STATUS_MAP: dict[str, str] = {
    "new": Order.STATUS_NEW,
    "needs_printing": Order.STATUS_NEEDS_PRINTING,
    "in_printing": Order.STATUS_IN_PRINTING,
    "ready_to_ship": Order.STATUS_READY_TO_SHIP,
    "shipped": Order.STATUS_SHIPPED,
    "cancelled": Order.STATUS_CANCELLED,
    "issue": Order.STATUS_ISSUE,
}

LINE_STATUS_MAP: dict[str, str] = {
    "new": OrderLine.STATUS_NEW,
    "to_be_printed": OrderLine.STATUS_TO_BE_PRINTED,
    "in_printing": OrderLine.STATUS_IN_PRINTING,
    "ready_ship": OrderLine.STATUS_READY_SHIP,
    "shipped": OrderLine.STATUS_SHIPPED,
    "cancelled": OrderLine.STATUS_CANCELLED,
}


class Command(BaseCommand):
    help = "Import production-ready CSV bundle for designs, inventory, and orders."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dir",
            default="docs/templates/data_input",
            help="Directory containing CSV bundle files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate only; do not write changes.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        bundle_dir = Path(options["dir"])
        dry_run = bool(options["dry_run"])

        if not bundle_dir.exists() or not bundle_dir.is_dir():
            raise CommandError(f"Bundle directory not found: {bundle_dir}")

        designs_csv = bundle_dir / "designs.csv"
        blank_skus_csv = bundle_dir / "blank_skus.csv"
        printed_skus_csv = bundle_dir / "printed_skus.csv"
        orders_csv = bundle_dir / "orders.csv"

        for file_path in [designs_csv, blank_skus_csv, printed_skus_csv, orders_csv]:
            if not file_path.exists():
                raise CommandError(f"Missing required file: {file_path}")

        designs_rows = self._read_csv(designs_csv)
        blank_rows = self._read_csv(blank_skus_csv)
        printed_rows = self._read_csv(printed_skus_csv)
        order_rows = self._read_csv(orders_csv)

        self.stdout.write(self.style.HTTP_INFO("CSV bundle parsed successfully:"))
        self.stdout.write(f"- designs.csv rows: {len(designs_rows)}")
        self.stdout.write(f"- blank_skus.csv rows: {len(blank_rows)}")
        self.stdout.write(f"- printed_skus.csv rows: {len(printed_rows)}")
        self.stdout.write(f"- orders.csv rows: {len(order_rows)}")

        self._validate_rows(designs_rows, blank_rows, printed_rows, order_rows)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete. No database changes applied."))
            return

        self._import_designs(designs_rows)
        self._import_blank_skus(blank_rows)
        self._import_printed_skus(printed_rows)
        self._import_orders(order_rows)

        self.stdout.write(self.style.SUCCESS("Production CSV import completed."))

    def _read_csv(self, file_path: Path) -> list[dict[str, str]]:
        """Read CSV into list of dict rows with normalized keys/values."""
        rows: list[dict[str, str]] = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise CommandError(f"Missing header row in {file_path}")
            for raw_row in reader:
                row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items()}
                if any(value for value in row.values()):
                    rows.append(row)
        return rows

    def _validate_rows(
        self,
        designs_rows: list[dict[str, str]],
        blank_rows: list[dict[str, str]],
        printed_rows: list[dict[str, str]],
        order_rows: list[dict[str, str]],
    ) -> None:
        """Validate required fields and status values before writing."""
        for index, row in enumerate(designs_rows, start=2):
            if not row.get("design_name"):
                raise CommandError(f"designs.csv row {index}: design_name is required")
            if not row.get("colour"):
                raise CommandError(f"designs.csv row {index}: colour is required")

        for index, row in enumerate(blank_rows, start=2):
            for field in ["fabric", "colour", "size", "on_hand"]:
                if not row.get(field):
                    raise CommandError(f"blank_skus.csv row {index}: {field} is required")

        for index, row in enumerate(printed_rows, start=2):
            for field in ["design_name", "colour", "size"]:
                if not row.get(field):
                    raise CommandError(f"printed_skus.csv row {index}: {field} is required")

        for index, row in enumerate(order_rows, start=2):
            status_value = (row.get("status") or "needs_printing").strip().lower()
            if status_value not in ORDER_STATUS_MAP:
                raise CommandError(f"orders.csv row {index}: unsupported status '{status_value}'")

    def _normalize_size(self, value: str) -> str:
        """Normalize size labels to canonical internal values."""
        normalized = value.strip().upper()
        if normalized == "2XL":
            return "XXL"
        if normalized == "3XL":
            return "XXXL"
        return normalized

    def _to_int(self, value: str, *, default: int = 0) -> int:
        """Convert numeric text into integer with default fallback."""
        if value in {"", None}:  # type: ignore[comparison-overlap]
            return default
        return int(float(str(value).strip()))

    def _import_designs(self, rows: list[dict[str, str]]) -> None:
        """Upsert design master and design assets from designs.csv."""
        for row in rows:
            design_name = row["design_name"]
            colour = row["colour"]

            design, _ = Design.objects.update_or_create(
                name=design_name,
                defaults={
                    "product_type": row.get("product_type") or Design.ProductType.TSHIRT,
                    "sub_category": row.get("sub_category") or Design.SubCategory.REGULAR,
                    "material": row.get("material") or "Cotton",
                    "fit": row.get("fit") or Design.Fit.REGULAR,
                    "has_variants": False,
                    "variants": [],
                    "notes": row.get("notes") or "",
                },
            )

            DesignAsset.objects.update_or_create(
                design=design,
                colour=colour,
                defaults={
                    "colour_hex": row.get("colour_hex") or "",
                    "artwork_url": row.get("artwork_url") or "https://example.com/artwork.png",
                    "mockup_url": row.get("mockup_url") or "",
                    "blank_fabric": row.get("blank_fabric") or "",
                    "print_areas": row.get("print_areas") or "Front",
                    "placement_note": row.get("placement_note") or "",
                },
            )

    def _import_blank_skus(self, rows: list[dict[str, str]]) -> None:
        """Upsert plain blank inventory rows from blank_skus.csv."""
        for row in rows:
            BlankSKU.objects.update_or_create(
                fabric=row["fabric"],
                colour=row["colour"],
                size=self._normalize_size(row["size"]),
                defaults={
                    "on_hand": self._to_int(row.get("on_hand", "0")),
                    "reserved": self._to_int(row.get("reserved", "0")),
                    "reorder_min": self._to_int(row.get("reorder_min", "0")),
                    "reorder_target": self._to_int(row.get("reorder_target", "0")),
                },
            )

    def _import_printed_skus(self, rows: list[dict[str, str]]) -> None:
        """Upsert printed inventory rows and link them to DesignAsset and BlankSKU."""
        for row in rows:
            design = Design.objects.filter(name__iexact=row["design_name"]).first()
            if design is None:
                raise CommandError(f"Design not found for printed SKU row: {row['design_name']}")

            colour = row["colour"]
            size = self._normalize_size(row["size"])
            variant = (row.get("variant") or "").strip() or None

            design_asset = DesignAsset.objects.filter(design=design, colour__iexact=colour).first()
            blank_fabric = (row.get("blank_fabric") or "").strip() or (design_asset.blank_fabric if design_asset else "")
            blank_sku = None
            if blank_fabric:
                blank_sku = BlankSKU.objects.filter(
                    fabric__iexact=blank_fabric,
                    colour__iexact=colour,
                    size__iexact=size,
                ).first()

            PrintedSKU.objects.update_or_create(
                design=design,
                variant=variant,
                colour=colour,
                size=size,
                defaults={
                    "design_asset": design_asset,
                    "blank_sku": blank_sku,
                    "on_hand": self._to_int(row.get("on_hand", "0")),
                    "reserved": self._to_int(row.get("reserved", "0")),
                    "is_active": True,
                    "buffer_min": self._to_int(row.get("buffer_min", "0")),
                    "buffer_target": self._to_int(row.get("buffer_target", "0")),
                    "buffer_max": self._to_int(row.get("buffer_max", "0")),
                    "is_test_data": False,
                },
            )

    def _import_orders(self, rows: list[dict[str, str]]) -> None:
        """Upsert orders and order lines from orders.csv."""
        line_counter: dict[str, int] = {}
        for row in rows:
            shopify_order_id = row["shopify_order_id"]
            status_value = (row.get("status") or "needs_printing").strip().lower()
            order_status = ORDER_STATUS_MAP[status_value]

            order, _ = Order.objects.update_or_create(
                shopify_order_id=shopify_order_id,
                defaults={
                    "order_no": row.get("order_no") or shopify_order_id,
                    "customer_name": row.get("customer_name") or "",
                    "email": row.get("email") or "",
                    "tags": [tag.strip() for tag in (row.get("tags") or "").split(",") if tag.strip()],
                    "status": order_status,
                    "shopify_fulfillment_status": row.get("fulfillment_status") or "",
                    "shopify_delivery_status": row.get("delivery_status") or "",
                    "raw_payload": {"source": "import_production_csv_bundle"},
                    "is_test_data": False,
                },
            )

            design = Design.objects.filter(name__iexact=row.get("product_name") or "").first()
            variant = (row.get("variant") or "").strip() or None
            colour = (row.get("colour") or "").strip()
            size = self._normalize_size(row.get("size") or "")
            quantity = self._to_int(row.get("quantity", "0"), default=0)

            printed_sku = None
            if design and colour and size:
                printed_sku = PrintedSKU.objects.filter(
                    design=design,
                    variant=variant,
                    colour__iexact=colour,
                    size__iexact=size,
                ).first()

            line_status_value = (row.get("line_status") or "to_be_printed").strip().lower()
            line_status = LINE_STATUS_MAP.get(line_status_value, OrderLine.STATUS_TO_BE_PRINTED)

            line_counter.setdefault(shopify_order_id, 0)
            line_counter[shopify_order_id] += 1
            default_line_id = f"{shopify_order_id}-line-{line_counter[shopify_order_id]}"
            shopify_line_id = (row.get("shopify_line_id") or "").strip() or default_line_id

            OrderLine.objects.update_or_create(
                shopify_line_id=shopify_line_id,
                defaults={
                    "order": order,
                    "product_name": row.get("product_name") or "",
                    "variant": row.get("variant") or "",
                    "size": size,
                    "quantity": quantity,
                    "printed_sku": printed_sku,
                    "is_bundle": False,
                    "bundle_components": [],
                    "status": line_status,
                },
            )
