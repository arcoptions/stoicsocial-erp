#!/usr/bin/env python
"""Debug script to check printed SKU availability."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order, OrderLine, PrintedSKU

print("=" * 60)
print("CHECKING PRINTED SKU AVAILABILITY")
print("=" * 60)

# Get a sample order with lines
order = Order.objects.filter(shopify_order_id='3634').first()
if order:
    print(f"\nOrder: {order.order_no} ({order.shopify_order_id})")
    for line in order.lines.all():
        print(f"\nLine: {line.product_name} (qty={line.quantity})")
        print(f"  Line Status: {line.status}")
        print(f"  Printed SKU ID: {line.printed_sku_id}")
        if line.printed_sku:
            sku = line.printed_sku
            print(f"  SKU: {sku.design.name} / {sku.variant} / {sku.colour} / {sku.size}")
            print(f"  Available: {sku.available}")
            print(f"  On-hand: {sku.on_hand}")
            print(f"  Reserved: {sku.reserved}")

print("\n" + "=" * 60)
print("TESTING LINE STATUS RESOLUTION")
print("=" * 60)

from core.services.shopify import _line_status_for_item

order = Order.objects.filter(shopify_order_id='3634').first()
if order:
    for line in order.lines.all():
        target = _line_status_for_item(line.printed_sku, line.quantity)
        print(f"\n{line.product_name} (qty={line.quantity})")
        print(f"  Current status: {line.status}")
        print(f"  Target status: {target}")
        print(f"  Should transition: {line.status != target}")
