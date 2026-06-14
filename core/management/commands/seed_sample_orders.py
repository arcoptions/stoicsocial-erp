from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import BlankSKU, DesignAsset, Order, OrderLine, PrintBatch, PrintJob, PrintJobLine, PrintedSKU, Vendor


@dataclass(frozen=True)
class SampleLineSpec:
    order_index: int
    printed_sku: PrintedSKU
    quantity: int
    status: str


class Command(BaseCommand):
    help = "Seed sample Order/OrderLine data so print-batch and receive views are non-empty."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Create repeatable sample operational data for local testing."""
        vendor = Vendor.objects.filter(is_active=True).order_by("name").first()
        if vendor is None:
            raise CommandError("No active vendor found. Import master data first.")

        printed_skus = list(PrintedSKU.objects.select_related("design").order_by("created_at")[:8])
        if len(printed_skus) < 4:
            raise CommandError("Need at least 4 PrintedSKU rows. Import sample_master_data.xlsx first.")

        self._cleanup_previous_seed_data()

        sample_orders = self._create_sample_orders(printed_skus)
        in_printing_orders = self._create_in_printing_orders(printed_skus)
        print_job = self._create_receive_queue(vendor, printed_skus)

        self.stdout.write(self.style.SUCCESS("Sample operational data seeded successfully."))
        self.stdout.write(f"- Orders created: {len(sample_orders) + len(in_printing_orders)}")
        self.stdout.write(f"- Order lines created: {OrderLine.objects.filter(shopify_line_id__startswith='sample-line-').count()}")
        self.stdout.write(f"- Receive queue PrintJob: {print_job.id}")

    def _cleanup_previous_seed_data(self) -> None:
        """Remove prior seeded records so command is idempotent."""
        seeded_job_ids = list(
            PrintJob.objects.filter(notes__icontains="seeded sample data").values_list("id", flat=True)
        )
        if seeded_job_ids:
            PrintJobLine.objects.filter(print_job_id__in=seeded_job_ids).delete()
            PrintJob.objects.filter(id__in=seeded_job_ids).delete()

        PrintBatch.objects.filter(notes__icontains="seeded sample data").delete()
        Order.objects.filter(shopify_order_id__startswith="sample-order-").delete()

    def _create_sample_orders(self, printed_skus: list[PrintedSKU]) -> list[Order]:
        """Create orders with TO_BE_PRINTED lines for print-batch suggestion."""
        orders: list[Order] = []
        line_specs = [
            SampleLineSpec(order_index=1, printed_sku=printed_skus[0], quantity=3, status=OrderLine.STATUS_TO_BE_PRINTED),
            SampleLineSpec(order_index=1, printed_sku=printed_skus[1], quantity=2, status=OrderLine.STATUS_TO_BE_PRINTED),
            SampleLineSpec(order_index=2, printed_sku=printed_skus[2], quantity=4, status=OrderLine.STATUS_TO_BE_PRINTED),
            SampleLineSpec(order_index=3, printed_sku=printed_skus[3], quantity=2, status=OrderLine.STATUS_TO_BE_PRINTED),
            SampleLineSpec(order_index=4, printed_sku=printed_skus[0], quantity=1, status=OrderLine.STATUS_TO_BE_PRINTED),
        ]

        for order_number in [1, 2, 3, 4]:
            order = Order.objects.create(
                shopify_order_id=f"sample-order-{order_number}",
                order_no=f"SAMPLE-ORD-{order_number:04d}",
                customer_name=f"Sample Customer {order_number}",
                email=f"sample{order_number}@example.com",
                tags=["sample", "print-batch"],
                status=Order.STATUS_NEEDS_PRINTING,
                shopify_fulfillment_status="unfulfilled",
                shopify_delivery_status="pending",
                raw_payload={"source": "seed_sample_orders"},
            )
            orders.append(order)

        line_counter = 1
        for spec in line_specs:
            order = orders[spec.order_index - 1]
            OrderLine.objects.create(
                order=order,
                shopify_line_id=f"sample-line-{line_counter}",
                product_name=spec.printed_sku.design.name,
                variant=spec.printed_sku.variant or "BASE",
                size=spec.printed_sku.size or "",
                quantity=spec.quantity,
                printed_sku=spec.printed_sku,
                is_bundle=False,
                bundle_components=[],
                status=spec.status,
            )
            line_counter += 1

        return orders

    def _create_in_printing_orders(self, printed_skus: list[PrintedSKU]) -> list[Order]:
        """Create in-printing orders to mirror real production states."""
        orders: list[Order] = []
        for order_number, sku, qty in [(5, printed_skus[4], 3), (6, printed_skus[5], 2)]:
            order = Order.objects.create(
                shopify_order_id=f"sample-order-{order_number}",
                order_no=f"SAMPLE-ORD-{order_number:04d}",
                customer_name=f"Sample Customer {order_number}",
                email=f"sample{order_number}@example.com",
                tags=["sample", "receive"],
                status=Order.STATUS_IN_PRINTING,
                shopify_fulfillment_status="unfulfilled",
                shopify_delivery_status="in_transit",
                raw_payload={"source": "seed_sample_orders"},
            )
            OrderLine.objects.create(
                order=order,
                shopify_line_id=f"sample-line-ip-{order_number}",
                product_name=sku.design.name,
                variant=sku.variant or "BASE",
                size=sku.size or "",
                quantity=qty,
                printed_sku=sku,
                is_bundle=False,
                bundle_components=[],
                status=OrderLine.STATUS_IN_PRINTING,
            )
            orders.append(order)
        return orders

    def _create_receive_queue(self, vendor: Vendor, printed_skus: list[PrintedSKU]) -> PrintJob:
        """Create one sent print job with lines so receive dashboard is populated."""
        batch = PrintBatch.objects.create(
            status=PrintBatch.STATUS_CONFIRMED,
            notes="Seeded sample data for receive queue",
            print_pack_path="",
        )
        print_job = PrintJob.objects.create(
            batch=batch,
            vendor=vendor,
            status=PrintJob.STATUS_SENT,
            sent_at=timezone.now(),
            notes="Seeded sample data for receive queue",
            pdf_url="",
        )

        receive_specs = [(printed_skus[4], 6), (printed_skus[5], 4), (printed_skus[6], 3)]
        for sku, qty_sent in receive_specs:
            blank_sku = self._resolve_blank_sku(sku)
            PrintJobLine.objects.create(
                print_job=print_job,
                printed_sku=sku,
                blank_sku=blank_sku,
                qty_sent=qty_sent,
                qty_received_good=0,
                qty_received_defective=0,
            )

        return print_job

    def _resolve_blank_sku(self, printed_sku: PrintedSKU) -> BlankSKU | None:
        """Find matching blank SKU using design asset fabric/colour/size heuristics."""
        asset = DesignAsset.objects.filter(design=printed_sku.design, colour__iexact=printed_sku.colour).first()
        if asset is None:
            return None

        query = BlankSKU.objects.filter(
            fabric__iexact=asset.blank_fabric,
            colour__iexact=printed_sku.colour,
        )
        if printed_sku.size:
            sized = query.filter(size__iexact=printed_sku.size).first()
            if sized is not None:
                return sized
        return query.first()
