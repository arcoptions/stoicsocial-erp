#!/usr/bin/env python
"""Create blank SKUs for all the new printed designs."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import BlankSKU, PrintedSKU, Design
from django.db import transaction

# Get all blank SKUs to understand the pattern
blanks = BlankSKU.objects.all()
print(f"Total blank SKUs in system: {blanks.count()}\n")

# Sample some blanks to see the structure
print("Sample blank SKUs:")
sample_blanks = blanks.values('fabric', 'colour', 'size').distinct()[:5]
for b in sample_blanks:
    print(f"  {b['fabric']} / {b['colour']} / {b['size']}")

# Get all printed SKUs that need blank matches
print("\n\nCreating blank SKUs for designs...")

printed_skus = PrintedSKU.objects.select_related('design').filter(
    design__name__in=[
        'Dulandhar - Konchem Dhula Ekkuva',
        'From 90s to 90ML',
        'Flashman Exam Vibe',
        'Current Rent etc',
        'Penguin Rahadhaari',
    ]
)

print(f"\nFound {printed_skus.count()} printed SKUs needing blank inventory\n")

# Assume a standard cotton t-shirt blank for all
blank_fabric = 'Cotton'
created_count = 0

with transaction.atomic():
    for p_sku in printed_skus:
        # Create corresponding blank SKU
        blank_sku, created = BlankSKU.objects.get_or_create(
            fabric=blank_fabric,
            colour=p_sku.colour,
            size=p_sku.size,
            defaults={
                'on_hand': 100,  # Default inventory
                'reserved': 0,
                'reorder_min': 5,
                'reorder_target': 20,
            }
        )
        if created:
            created_count += 1
            print(f"✓ Created blank SKU: {blank_fabric} / {p_sku.colour} / {p_sku.size}")

print(f"\n✓ Created {created_count} new blank SKUs")

# Verify we now have blanks for the problematic printed SKUs
print("\n\nVerifying coverage:")
problem_printed = PrintedSKU.objects.select_related('design').filter(
    design__name='Dulandhar - Konchem Dhula Ekkuva'
)

for p_sku in problem_printed:
    blank_match = BlankSKU.objects.filter(
        colour=p_sku.colour,
        size=p_sku.size,
    ).exists()
    status = "✓" if blank_match else "✗"
    print(f"{status} {p_sku.design.name} / {p_sku.colour} / {p_sku.size}")
