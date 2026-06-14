#!/usr/bin/env python
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Order
from django.db.models import Count

statuses = Order.objects.values('status').annotate(count=Count('id')).order_by('status')
print('Order Status Breakdown:')
for s in statuses:
    print(f"  {s['status']}: {s['count']} orders")

print('\nNew Orders (first 5):')
new_orders = Order.objects.filter(status='new').values('id', 'reference_shopify_id', 'lines__printed_sku_id')[:5]
for o in new_orders:
    print(f"  {o['reference_shopify_id']} - has printed SKU: {o['lines__printed_sku_id'] is not None}")
