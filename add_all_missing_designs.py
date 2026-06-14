#!/usr/bin/env python
"""Add all missing designs from unmatched order lines."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Design, PrintedSKU, OrderLine
from collections import Counter
from django.db import transaction

# Find all unique product names that don't have a Design yet
unmatched_lines = OrderLine.objects.filter(printed_sku__isnull=True)
missing_product_names = set(unmatched_lines.values_list('product_name', flat=True))

# Also get product names that ARE matched but might need more size/color combos
all_product_names = set(OrderLine.objects.values_list('product_name', flat=True))

# Find which ones don't have a Design yet
existing_designs = set(Design.objects.values_list('name', flat=True))
new_designs = missing_product_names - existing_designs

print(f"Creating {len(new_designs)} new designs and SKUs...\n")

# Common sizes and colors
all_sizes = ["S", "M", "L", "XL", "XXL", "3XL"]
all_colors = ["Black", "White", "Navy", "Red"]
variant = "BASE"

with transaction.atomic():
    created_count = 0
    for design_name in sorted(new_designs):
        design, created = Design.objects.get_or_create(
            name=design_name,
            defaults={"notes": "Auto-created from order webhook"}
        )
        if created:
            created_count += 1
            print(f"✓ Created design: {design_name}")
        
        # Create SKUs for all size/color combinations
        for size in all_sizes:
            for color in all_colors:
                sku_obj, created = PrintedSKU.objects.get_or_create(
                    design=design,
                    variant=variant,
                    colour=color,
                    size=size,
                    defaults={
                        "on_hand": 0,
                        "reserved": 0,
                        "buffer_min": 0,
                        "buffer_target": 0,
                        "buffer_max": 0,
                    }
                )

print(f"\nCreated {created_count} new designs")

# Now match order lines to the SKUs
print("\nMatching order lines to SKUs...")

unmatched = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"Before: {unmatched.count()} unmatched order lines")

matched_count = 0
for line in unmatched:
    # Try to find a matching PrintedSKU by product name and size
    matching_sku = PrintedSKU.objects.filter(
        design__name=line.product_name,
        size=line.size,
        colour="Black",  # Try Black first
    ).first()
    
    if matching_sku:
        line.printed_sku = matching_sku
        line.save(update_fields=['printed_sku'])
        matched_count += 1

unmatched_after = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"After: {unmatched_after.count()} unmatched order lines")
print(f"Newly matched: {matched_count} lines")

# Check order status
from core.models import Order
new_orders = Order.objects.filter(status='new')
print(f"\nOrders still in 'new' status: {new_orders.count()}")
for order in new_orders:
    lines = order.lines.all()
    unmatched_lines = lines.filter(printed_sku__isnull=True).count()
    if unmatched_lines > 0:
        print(f"  {order.order_no}: {lines.count()} lines, {unmatched_lines} still unmatched")
        for line in lines.filter(printed_sku__isnull=True):
            print(f"    - {line.product_name} / {line.size}")
