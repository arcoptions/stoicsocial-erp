from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import BlankSKU, DesignAsset, Order, OrderLine, PrintBatch, PrintJob, PrintJobLine, PrintedSKU, Vendor
from core.services import pdf


SEED_TAG = "[QA_SEED]"


@dataclass(frozen=True)
class QaOrderSpec:
    """Specification for a seeded QA order scenario."""

    code: str
    status: str
    line_statuses: list[str]
    ages_days: int
    tags: list[str]
    fulfillment_status: str


class Command(BaseCommand):
    help = "Seed comprehensive QA scenarios for order lifecycle, print batch and receive testing."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Create repeatable QA fixtures across all operational states."""
        vendor = Vendor.objects.filter(is_active=True).order_by("name").first()
        if vendor is None:
            raise CommandError("No active vendor found. Seed master data first.")

        skus = list(PrintedSKU.objects.select_related("design").order_by("created_at")[:12])
        if len(skus) < 8:
            raise CommandError("Need at least 8 PrintedSKU rows before seeding QA scenarios.")

        self._cleanup_existing_seed_data()
        orders = self._seed_orders(skus)
        jobs = self._seed_print_jobs(vendor, skus)

        self.stdout.write(self.style.SUCCESS("QA scenarios seeded successfully."))
        self.stdout.write(f"- Orders: {len(orders)}")
        self.stdout.write(f"- Order lines: {OrderLine.objects.filter(shopify_line_id__startswith='qa-line-').count()}")
        self.stdout.write(f"- Print jobs: {len(jobs)}")
        self.stdout.write(f"- Sent jobs visible in Receive: {PrintJob.objects.filter(status=PrintJob.STATUS_SENT, notes__icontains=SEED_TAG).count()}")

    def _cleanup_existing_seed_data(self) -> None:
        """Delete old QA fixtures so the command is idempotent."""
        seeded_job_ids = list(PrintJob.objects.filter(notes__icontains=SEED_TAG).values_list("id", flat=True))
        if seeded_job_ids:
            PrintJob.objects.filter(id__in=seeded_job_ids).delete()
        PrintBatch.objects.filter(notes__icontains=SEED_TAG).delete()
        Order.objects.filter(shopify_order_id__startswith="qa-order-").delete()

    def _seed_orders(self, skus: list[PrintedSKU]) -> list[Order]:
        """Create orders covering all business states and age buckets."""
        now = timezone.now()
        specs: list[QaOrderSpec] = [
            QaOrderSpec(
                code="new-fresh",
                status=Order.STATUS_NEW,
                line_statuses=[OrderLine.STATUS_NEW],
                ages_days=0,
                tags=["qa", "new"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="needs-printing-fresh",
                status=Order.STATUS_NEEDS_PRINTING,
                line_statuses=[OrderLine.STATUS_TO_BE_PRINTED],
                ages_days=1,
                tags=["qa", "needs-printing"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="needs-printing-stale-4d",
                status=Order.STATUS_NEEDS_PRINTING,
                line_statuses=[OrderLine.STATUS_TO_BE_PRINTED],
                ages_days=4,
                tags=["qa", "stale", "4d"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="in-printing-fresh",
                status=Order.STATUS_IN_PRINTING,
                line_statuses=[OrderLine.STATUS_IN_PRINTING],
                ages_days=1,
                tags=["qa", "in-printing"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="in-printing-urgent-8d",
                status=Order.STATUS_IN_PRINTING,
                line_statuses=[OrderLine.STATUS_IN_PRINTING],
                ages_days=8,
                tags=["qa", "urgent", "8d"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="ready-to-ship",
                status=Order.STATUS_READY_TO_SHIP,
                line_statuses=[OrderLine.STATUS_READY_SHIP],
                ages_days=2,
                tags=["qa", "ready"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="shipped",
                status=Order.STATUS_SHIPPED,
                line_statuses=[OrderLine.STATUS_SHIPPED],
                ages_days=3,
                tags=["qa", "shipped"],
                fulfillment_status="fulfilled",
            ),
            QaOrderSpec(
                code="cancelled",
                status=Order.STATUS_CANCELLED,
                line_statuses=[OrderLine.STATUS_CANCELLED],
                ages_days=2,
                tags=["qa", "cancelled"],
                fulfillment_status="voided",
            ),
            QaOrderSpec(
                code="issue",
                status=Order.STATUS_ISSUE,
                line_statuses=[OrderLine.STATUS_TO_BE_PRINTED],
                ages_days=5,
                tags=["qa", "issue"],
                fulfillment_status="unfulfilled",
            ),
            QaOrderSpec(
                code="mixed-priority",
                status=Order.STATUS_NEEDS_PRINTING,
                line_statuses=[OrderLine.STATUS_TO_BE_PRINTED, OrderLine.STATUS_READY_SHIP],
                ages_days=2,
                tags=["qa", "mixed"],
                fulfillment_status="partial",
            ),
        ]

        orders: list[Order] = []
        line_counter = 1
        sku_index = 0

        for idx, spec in enumerate(specs, start=1):
            order = Order.objects.create(
                shopify_order_id=f"qa-order-{idx:03d}",
                order_no=f"QA-ORD-{idx:04d}",
                customer_name=f"QA Customer {idx}",
                email=f"qa{idx}@example.com",
                tags=[SEED_TAG, *spec.tags],
                status=spec.status,
                shopify_fulfillment_status=spec.fulfillment_status,
                shopify_delivery_status="pending",
                raw_payload={"source": "seed_qa_scenarios", "scenario": spec.code},
            )
            orders.append(order)

            for status in spec.line_statuses:
                sku = skus[sku_index % len(skus)]
                quantity = 1 + (sku_index % 3)
                sku_index += 1
                OrderLine.objects.create(
                    order=order,
                    shopify_line_id=f"qa-line-{line_counter:04d}",
                    product_name=sku.design.name,
                    variant=sku.variant or "BASE",
                    size=sku.size or "",
                    quantity=quantity,
                    printed_sku=sku,
                    is_bundle=False,
                    bundle_components=[],
                    status=status,
                )
                line_counter += 1

            created_at = now - timedelta(days=spec.ages_days)
            Order.objects.filter(id=order.id).update(created_at=created_at)

        # Edge case: zero-line order
        edge_order = Order.objects.create(
            shopify_order_id="qa-order-999",
            order_no="QA-ORD-0999",
            customer_name="QA Empty Order",
            email="qa-empty@example.com",
            tags=[SEED_TAG, "edge", "zero-lines"],
            status=Order.STATUS_NEW,
            shopify_fulfillment_status="",
            shopify_delivery_status="",
            raw_payload={"source": "seed_qa_scenarios", "scenario": "zero-lines"},
        )
        Order.objects.filter(id=edge_order.id).update(created_at=now - timedelta(days=1))
        orders.append(edge_order)

        return orders

    def _seed_print_jobs(self, vendor: Vendor, skus: list[PrintedSKU]) -> list[PrintJob]:
        """Create print jobs across receive states: sent, partially received, received."""
        now = timezone.now()
        jobs: list[PrintJob] = []

        scenario_specs = [
            ("sent", PrintJob.STATUS_SENT, [
                (skus[0], 6, 0, 0),
                (skus[1], 4, 0, 0),
                (skus[2], 3, 0, 0),
            ]),
            ("partial", PrintJob.STATUS_PARTIALLY_RECEIVED, [
                (skus[3], 8, 6, 1),
                (skus[4], 5, 5, 0),
                (skus[5], 4, 2, 1),
            ]),
            ("received", PrintJob.STATUS_RECEIVED, [
                (skus[6], 5, 5, 0),
                (skus[7], 7, 7, 0),
            ]),
        ]

        for index, (code, status, line_specs) in enumerate(scenario_specs, start=1):
            batch = PrintBatch.objects.create(
                status=PrintBatch.STATUS_CONFIRMED if status != PrintJob.STATUS_RECEIVED else PrintBatch.STATUS_RECEIVED,
                notes=f"{SEED_TAG} print-batch {code}",
                print_pack_path="",
            )
            job = PrintJob.objects.create(
                batch=batch,
                vendor=vendor,
                status=status,
                sent_at=now - timedelta(days=index),
                expected_at=now + timedelta(days=2),
                received_at=(now - timedelta(hours=4)) if status == PrintJob.STATUS_RECEIVED else None,
                notes=f"{SEED_TAG} print-job {code}",
                pdf_url="",
            )
            jobs.append(job)

            for sku, qty_sent, qty_good, qty_def in line_specs:
                PrintJobLine.objects.create(
                    print_job=job,
                    printed_sku=sku,
                    blank_sku=self._resolve_blank_sku(sku),
                    qty_sent=qty_sent,
                    qty_received_good=qty_good,
                    qty_received_defective=qty_def,
                    shortfall_flagged=(qty_good + qty_def) < qty_sent,
                )

            # Generate print pack where possible so links exist in UI.
            try:
                pdf.build_print_pack_pdf(str(job.id))
            except Exception:
                # Keep seeding resilient even if image/PDF rendering fails on one environment.
                pass

        return jobs

    def _resolve_blank_sku(self, printed_sku: PrintedSKU) -> BlankSKU | None:
        """Resolve matching blank SKU by design asset fabric, colour and size."""
        asset = DesignAsset.objects.filter(design=printed_sku.design, colour__iexact=printed_sku.colour).first()
        if asset is None:
            asset = DesignAsset.objects.filter(design=printed_sku.design).first()
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
