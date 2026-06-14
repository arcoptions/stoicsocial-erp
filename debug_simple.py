#!/usr/bin/env python
"""Debug script - simpler version."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order, OrderLine

# Get all orders with status new
new_orders = Order.objects.filter(status='new')
print(f"Total NEW orders: {new_orders.count()}")

# Check each one
for order in new_orders:
    lines = order.lines.all()
    print(f"\n{order.order_no or order.shopify_order_id}: {lines.count()} lines, status={order.status}")
    for i, line in enumerate(lines):
        print(f"  Line {i+1}: {line.product_name}")
        print(f"    Status: {line.status}")
        print(f"    Qty: {line.quantity}")
        print(f"    PrintedSKU ID: {line.printed_sku_id}")
        if line.printed_sku:
            sku = line.printed_sku
            print(f"    SKU Available: {sku.available}")
