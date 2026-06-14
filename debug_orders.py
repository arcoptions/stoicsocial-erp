#!/usr/bin/env python
"""Debug script to check why orders are still new."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order, OrderLine

print("=" * 60)
print("CHECKING ORDERS")
print("=" * 60)

# Check the order with lines
order = Order.objects.filter(shopify_order_id='3634').first()
if order:
    print(f"\nOrder: {order.order_no} ({order.shopify_order_id})")
    print(f"Status: {order.status}")
    print(f"Lines: {order.lines.count()}")
    for line in order.lines.all():
        print(f"  - {line.product_name}: {line.status} (qty={line.quantity}, sku={line.printed_sku_id})")

# Check the empty order
order2 = Order.objects.filter(order_no='QA-ORD-0999').first()
if order2:
    print(f"\nOrder: {order2.order_no} ({order2.shopify_order_id})")
    print(f"Status: {order2.status}")
    print(f"Lines: {order2.lines.count()}")

# Check QA-ORD-0001
order3 = Order.objects.filter(order_no='QA-ORD-0001').first()
if order3:
    print(f"\nOrder: {order3.order_no} ({order3.shopify_order_id})")
    print(f"Status: {order3.status}")
    print(f"Lines: {order3.lines.count()}")
    for line in order3.lines.all():
        print(f"  - {line.product_name}: {line.status} (qty={line.quantity}, sku={line.printed_sku_id})")

print("\n" + "=" * 60)
print("ALL ORDERS WITH STATUS NEW")
print("=" * 60)
new_orders = Order.objects.filter(status='new').order_by('created_at')
print(f"Total NEW orders: {new_orders.count()}")
for order in new_orders[:10]:
    print(f"\n{order.order_no or order.shopify_order_id}: {order.lines.count()} lines")
    for line in order.lines.all():
        print(f"  - {line.status}: {line.product_name}")
