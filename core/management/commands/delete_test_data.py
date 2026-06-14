"""Delete all test orders and inventory marked with is_test_data flag."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from core.models import Order, OrderLine, PrintedSKU


class Command(BaseCommand):
    help = "Delete all test orders and inventory marked with is_test_data flag"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--no-confirm",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        no_confirm = options["no_confirm"]

        # Count test data
        test_orders = Order.objects.filter(is_test_data=True)
        test_order_lines = OrderLine.objects.filter(is_test_data=True)
        test_printed_skus = PrintedSKU.objects.filter(is_test_data=True)

        order_count = test_orders.count()
        order_line_count = test_order_lines.count()
        printed_sku_count = test_printed_skus.count()

        self.stdout.write(f"\n📊 Test Data Summary:")
        self.stdout.write(f"  Orders: {order_count}")
        self.stdout.write(f"  Order Lines: {order_line_count}")
        self.stdout.write(f"  PrintedSKUs: {printed_sku_count}")
        self.stdout.write(f"  Total items to delete: {order_count + order_line_count + printed_sku_count}")

        if not (order_count or order_line_count or printed_sku_count):
            self.stdout.write(self.style.WARNING("No test data found to delete"))
            return

        if not no_confirm:
            response = input("\n⚠️  This will permanently delete all test data. Proceed? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                self.stdout.write(self.style.WARNING("Deletion cancelled"))
                return

        # Delete order lines first (due to FK constraints)
        self.stdout.write("\n🗑️  Deleting test order lines...")
        test_order_lines.delete()
        self.stdout.write(self.style.SUCCESS(f"  ✅ Deleted {order_line_count} order lines"))

        # Delete orders
        self.stdout.write("🗑️  Deleting test orders...")
        test_orders.delete()
        self.stdout.write(self.style.SUCCESS(f"  ✅ Deleted {order_count} orders"))

        # Delete printed SKUs
        self.stdout.write("🗑️  Deleting test printed SKUs...")
        test_printed_skus.delete()
        self.stdout.write(self.style.SUCCESS(f"  ✅ Deleted {printed_sku_count} printed SKUs"))

        self.stdout.write(self.style.SUCCESS("\n✅ All test data has been deleted"))
