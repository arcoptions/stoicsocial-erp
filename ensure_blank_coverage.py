#!/usr/bin/env python
"""Ensure all printed SKUs have matching blank SKU inventory."""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import BlankSKU, PrintedSKU
from django.db import transaction

# Match all printed SKU color/size combos with existing blank fabrics
# Get the most common fabric type from existing blanks
existing_blanks = BlankSKU.objects.all()
fabric_counts = {}
for b in existing_blanks:
    fabric_counts[b.fabric] = fabric_counts.get(b.fabric, 0) + 1

print(f"Existing blank fabrics:")
for fabric, count in sorted(fabric_counts.items(), key=lambda x: -x[1]):
    print(f"  {fabric}: {count} SKUs")

standard_fabric = max(fabric_counts.items(), key=lambda x: x[1])[0]
print(f"\nUsing standard fabric: {standard_fabric}\n")

# Get all color/size combinations from printed SKUs
printed_colors_sizes = PrintedSKU.objects.filter(size__isnull=False).values('colour', 'size').distinct().order_by('colour', 'size')

print(f"Creating blanks for all printed color/size combos using {standard_fabric}...\n")

created_count = 0
with transaction.atomic():
    for item in printed_colors_sizes:
        blank_sku, created = BlankSKU.objects.get_or_create(
            fabric=standard_fabric,
            colour=item['colour'],
            size=item['size'],
            defaults={
                'on_hand': 50,
                'reserved': 0,
                'reorder_min': 5,
                'reorder_target': 20,
            }
        )
        if created:
            created_count += 1
            print(f"✓ {standard_fabric} / {item['colour']} / {item['size']}")

print(f"\n✓ Created {created_count} new blank SKUs with standard fabric")

# Final verification
print(f"\nTotal blank SKUs now: {BlankSKU.objects.count()}")
