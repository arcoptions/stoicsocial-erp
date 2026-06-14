"""Export a CSV template for importing test orders."""

from __future__ import annotations

import csv
from typing import Any

from django.core.management.base import BaseCommand

from core.models import Design, PrintedSKU


class Command(BaseCommand):
    help = "Export a CSV template for importing test orders"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--output",
            type=str,
            default="test_orders_template.csv",
            help="Output CSV file path (default: test_orders_template.csv)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        output_file = options["output"]

        try:
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow([
                    "order_id",
                    "customer_name",
                    "email",
                    "design_name",
                    "colour",
                    "size",
                    "quantity",
                ])

                # Write example rows with actual designs from database
                designs = Design.objects.all()[:5]
                for i, design in enumerate(designs, 1):
                    # Get a printed SKU for this design
                    printed_sku = PrintedSKU.objects.filter(design=design).first()
                    if printed_sku:
                        writer.writerow([
                            f"TEST-{i:04d}",
                            f"Test Customer {i}",
                            f"test{i}@example.com",
                            design.name,
                            printed_sku.colour,
                            printed_sku.size or "L",
                            2,
                        ])

                # Add empty rows for user input
                for i in range(5, 11):
                    writer.writerow([
                        f"TEST-{i:04d}",
                        f"Test Customer {i}",
                        f"test{i}@example.com",
                        "",
                        "",
                        "",
                        "",
                    ])

            self.stdout.write(self.style.SUCCESS(f"✅ Template exported to: {output_file}"))
            self.stdout.write("\n📝 Instructions:")
            self.stdout.write("  1. Open the CSV file in a spreadsheet application")
            self.stdout.write("  2. Fill in the empty rows with your test data")
            self.stdout.write("  3. Run: python manage.py import_test_orders <csv_file>")
            self.stdout.write("\n⚠️  Note: design_name and colour must match existing designs in database")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating template: {e}"))
