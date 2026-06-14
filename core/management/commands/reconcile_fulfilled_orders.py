from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Order, OrderLine
from core.services.shopify import sync_fulfillment


class Command(BaseCommand):
    help = "Backfill internal statuses for orders already marked fulfilled in Shopify."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without persisting updates.",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Repair historical fulfilled orders still stuck in printing states."""
        dry_run = bool(options.get("dry_run", False))
        candidates = (
            Order.objects.filter(shopify_fulfillment_status__iexact="fulfilled")
            .exclude(status=Order.STATUS_SHIPPED)
            .prefetch_related("lines")
            .order_by("created_at")
        )

        scanned = candidates.count()
        updated = 0

        for order in candidates:
            live_lines = list(order.lines.exclude(status=OrderLine.STATUS_CANCELLED))
            if not live_lines:
                if dry_run:
                    self.stdout.write(f"[DRY] {order.shopify_order_id}: no live lines, would set order to shipped")
                else:
                    order.status = Order.STATUS_SHIPPED
                    order.save(update_fields=["status", "updated_at"])
                updated += 1
                continue

            payload = {
                "order_id": order.shopify_order_id,
                "status": "fulfilled",
                "fulfillment_status": "fulfilled",
                "delivery_status": order.shopify_delivery_status or "",
                "line_items": [{"id": line.shopify_line_id} for line in live_lines],
            }

            if dry_run:
                self.stdout.write(
                    f"[DRY] {order.shopify_order_id}: would reconcile {len(live_lines)} lines to shipped"
                )
                updated += 1
                continue

            with transaction.atomic():
                sync_fulfillment(payload)
            updated += 1

        mode = "DRY-RUN" if dry_run else "APPLIED"
        self.stdout.write(self.style.SUCCESS(f"{mode}: scanned={scanned}, updated={updated}"))
