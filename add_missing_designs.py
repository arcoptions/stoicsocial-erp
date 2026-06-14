#!/usr/bin/env python
"""Add missing designs that new orders are waiting for."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Design, PrintedSKU
from django.db import transaction

# Missing designs from the new orders
missing_designs = [
    "Mana Aura Ekkuva",
    "Upside Down ki Dhaaredhi", 
    "Dulandhar - Konchem Dhula Ekkuva",
    "Shades of life",
]

# Sizes needed (from the order lines we found)
sizes_needed = ["XL", "XXL"]
colors = ["Black"]  # Default color
variant = "BASE"

print("Adding missing designs and SKUs...")
with transaction.atomic():
    for design_name in missing_designs:
        design, created = Design.objects.get_or_create(
            name=design_name,
            defaults={"notes": f"Auto-created from order webhook"}
        )
        if created:
            print(f"✓ Created design: {design_name}")
        else:
            print(f"  Design already exists: {design_name}")
        
        # Create PrintedSKUs for each size/color combination
        for size in sizes_needed:
            for color in colors:
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
                if created:
                    print(f"  ✓ Created SKU: {design_name} / {variant} / {color} / {size}")
                else:
                    print(f"    SKU already exists: {design_name} / {variant} / {color} / {size}")

print("\nDone! Now trying to match order lines to these new SKUs...")

# Try to match order lines to the new SKUs
from core.models import OrderLine
unmatched = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"\nBefore: {unmatched.count()} unmatched order lines")

matched_count = 0
for line in unmatched:
    # Try to find a matching PrintedSKU by product name and size
    matching_sku = PrintedSKU.objects.filter(
        design__name=line.product_name,
        size=line.size,
    ).first()
    
    if matching_sku:
        line.printed_sku = matching_sku
        line.save(update_fields=['printed_sku'])
        matched_count += 1
        print(f"  Matched: {line.product_name} / {line.size} -> SKU {matching_sku.id}")

unmatched_after = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"\nAfter: {unmatched_after.count()} unmatched order lines")
print(f"Newly matched: {matched_count} lines")

# Check if orders can now transition to IN_PRINTING
from core.models import Order
new_orders = Order.objects.filter(status='new')
print(f"\nOrders still in 'new' status: {new_orders.count()}")
for order in new_orders:
    lines = order.lines.all()
    unmatched_lines = lines.filter(printed_sku__isnull=True).count()
    print(f"  {order.order_no}: {lines.count()} lines, {unmatched_lines} unmatched")
