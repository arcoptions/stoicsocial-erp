"""Import test orders from CSV file for testing different scenarios."""

from __future__ import annotations

import csv
from typing import Any

from django.core.management.base import BaseCommand

from core.models import Design, Order, OrderLine, PrintedSKU


class Command(BaseCommand):
    help = "Import test orders from CSV file for testing different scenarios"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to CSV file with test orders",
        )
        parser.add_argument(
            "--no-confirm",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        csv_file = options["csv_file"]
        no_confirm = options["no_confirm"]

        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    self.stdout.write(self.style.ERROR("CSV file is empty"))
                    return

                # Expected columns: order_id, customer_name, email, design_name, colour, size, quantity
                required_fields = {"order_id", "customer_name", "email", "design_name", "colour", "size", "quantity"}
                missing_fields = required_fields - set(reader.fieldnames or [])
                if missing_fields:
                    self.stdout.write(
                        self.style.ERROR(f"CSV missing required columns: {', '.join(missing_fields)}")
                    )
                    return

                rows = list(reader)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"File not found: {csv_file}"))
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading CSV: {e}"))
            return

        if not rows:
            self.stdout.write(self.style.WARNING("CSV file has no data rows"))
            return

        # Preview
        self.stdout.write(f"\n📋 Found {len(rows)} test orders to import:")
        for i, row in enumerate(rows[:5], 1):
            self.stdout.write(
                f"  {i}. {row['order_id']} - {row['design_name']} ({row['colour']}) Size {row['size']} x{row['quantity']}"
            )
        if len(rows) > 5:
            self.stdout.write(f"  ... and {len(rows) - 5} more")

        if not no_confirm:
            response = input("\n✅ Proceed with import? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                self.stdout.write(self.style.WARNING("Import cancelled"))
                return

        # Import
        imported_count = 0
        error_count = 0
        errors = []

        for row in rows:
            try:
                order_id = row["order_id"].strip()
                customer_name = row["customer_name"].strip()
                email = row["email"].strip()
                design_name = row["design_name"].strip()
                colour = row["colour"].strip()
                size = row["size"].strip()
                quantity = int(row["quantity"].strip())

                # Check if design exists
                try:
                    design = Design.objects.get(name=design_name)
                except Design.DoesNotExist:
                    raise ValueError(f"Design '{design_name}' not found")

                # Check if printed SKU exists
                try:
                    printed_sku = PrintedSKU.objects.get(design=design, colour=colour, size=size)
                except PrintedSKU.DoesNotExist:
                    raise ValueError(f"PrintedSKU not found: {design_name} / {colour} / {size}")

                # Create or get order
                order, created = Order.objects.get_or_create(
                    shopify_order_id=order_id,
                    defaults={
                        "customer_name": customer_name,
                        "email": email,
                        "is_test_data": True,
                    },
                )

                # Create order line
                OrderLine.objects.create(
                    order=order,
                    printed_sku=printed_sku,
                    quantity_requested=quantity,
                    is_test_data=True,
                )

                imported_count += 1
            except Exception as e:
                error_count += 1
                errors.append(f"Row {len(errors) + 1}: {row.get('order_id', 'unknown')} - {str(e)}")

        # Summary
        self.stdout.write(self.style.SUCCESS(f"\n✅ Imported {imported_count} test orders"))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"❌ Failed to import {error_count} rows:"))
            for error in errors[:10]:
                self.stdout.write(f"  - {error}")
            if len(errors) > 10:
                self.stdout.write(f"  ... and {len(errors) - 10} more errors")
