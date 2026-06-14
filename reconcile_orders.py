#!/usr/bin/env python
"""Reconcile stuck new orders."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order
from core.services.shopify import _reconcile_new_orders, _recompute_order, _apply_live_state_to_order

print("=" * 60)
print("RECONCILING NEW ORDERS")
print("=" * 60)

# Show before state
new_orders = Order.objects.filter(status='new')
print(f"\nBefore: {new_orders.count()} orders in NEW status")
for order in new_orders:
    print(f"  - {order.order_no or order.shopify_order_id}: {order.lines.count()} lines")

# Reconcile
count = _reconcile_new_orders()
print(f"\nProcessed: {count} orders")

# Show after state
new_orders = Order.objects.filter(status='new')
print(f"\nAfter: {new_orders.count()} orders in NEW status")

all_orders = Order.objects.filter(status__in=['needs_printing', 'ready_to_ship', 'issue', 'to_be_printed'])
print(f"\nOrders in other statuses:")
statuses = {}
for order in Order.objects.all():
    if order.status not in statuses:
        statuses[order.status] = 0
    statuses[order.status] += 1

for status, count in sorted(statuses.items()):
    print(f"  {status}: {count}")
