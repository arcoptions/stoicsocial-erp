#!/usr/bin/env python
"""Fill in missing size/color SKUs for designs that were only partially created."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Design, PrintedSKU, OrderLine
from django.db import transaction

all_sizes = ["S", "M", "L", "XL", "XXL", "3XL"]
all_colors = ["Black", "White", "Navy", "Red"]
variant = "BASE"

# These designs were created but only with XL and XXL
incomplete_designs = [
    "Mana Aura Ekkuva",
    "Dulandhar - Konchem Dhula Ekkuva",
    "Shades of life",
]

print("Filling in missing size SKUs for incomplete designs...\n")

with transaction.atomic():
    for design_name in incomplete_designs:
        design = Design.objects.get(name=design_name)
        
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
                if created:
                    print(f"✓ Created SKU: {design_name} / {variant} / {color} / {size}")

# Handle the blank size case for TFI Meme Calendar 2026
print("\nHandling blank size case...")
design, _ = Design.objects.get_or_create(
    name="TFI Meme Calendar 2026",
    defaults={"notes": "Auto-created from order webhook"}
)

# Create SKUs with NULL/blank size
for color in all_colors:
    sku_obj, created = PrintedSKU.objects.get_or_create(
        design=design,
        variant=variant,
        colour=color,
        size=None,  # Blank size
        defaults={
            "on_hand": 0,
            "reserved": 0,
            "buffer_min": 0,
            "buffer_target": 0,
            "buffer_max": 0,
        }
    )
    if created:
        print(f"✓ Created SKU: TFI Meme Calendar 2026 / {variant} / {color} / (no size)")

# Now match remaining lines
print("\nMatching remaining order lines...")
unmatched = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"Before: {unmatched.count()} unmatched order lines")

matched_count = 0
for line in unmatched:
    # For lines with size, match by design + size
    if line.size:
        matching_sku = PrintedSKU.objects.filter(
            design__name=line.product_name,
            size=line.size,
            colour="Black",
        ).first()
    else:
        # For lines without size, match by design alone with NULL size
        matching_sku = PrintedSKU.objects.filter(
            design__name=line.product_name,
            size__isnull=True,
            colour="Black",
        ).first()
    
    if matching_sku:
        line.printed_sku = matching_sku
        line.save(update_fields=['printed_sku'])
        matched_count += 1

unmatched_after = OrderLine.objects.filter(printed_sku__isnull=True)
print(f"After: {unmatched_after.count()} unmatched order lines")
print(f"Newly matched: {matched_count} lines")

# Final check
from core.models import Order
new_orders = Order.objects.filter(status='new')
print(f"\n✓ All unmatched order lines resolved!" if unmatched_after.count() == 0 else f"\nStill have {unmatched_after.count()} unmatched lines")
print(f"Orders ready to process: {new_orders.count()}")
