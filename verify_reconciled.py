#!/usr/bin/env python
"""Verify the reconciled orders."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order

# Check the specific orders from the screenshot
orders_to_check = [
    ('QA-ORD-0001', 'qa-order-001'),
    ('QA-ORD-0999', 'qa-order-999'),
    ('#3634', None),
    ('#3633', None),
    ('#3632', None),
]

print("=" * 70)
print("RECONCILED ORDER STATUSES")
print("=" * 70)

for order_no, shopify_id in orders_to_check:
    if shopify_id:
        order = Order.objects.filter(shopify_order_id=shopify_id).first()
    else:
        order = Order.objects.filter(order_no=order_no).first()
    
    if order:
        print(f"\n{order.order_no or order.shopify_order_id}:")
        print(f"  Status: {order.status}")
        print(f"  Lines: {order.lines.count()}")
        for line in order.lines.all():
            print(f"    - {line.product_name}: {line.status} (qty={line.quantity}, sku={line.printed_sku_id is not None})")
    else:
        print(f"\n{order_no}: NOT FOUND")
