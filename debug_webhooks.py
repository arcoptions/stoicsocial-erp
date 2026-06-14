#!/usr/bin/env python
"""Debug - check webhook events for these orders."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.models import Order, WebhookEvent
import json

print("=" * 60)
print("WEBHOOK EVENTS FOR NEW ORDERS")
print("=" * 60)

new_orders = Order.objects.filter(status='new')
for order in new_orders[:2]:  # Just check first 2
    print(f"\n{order.order_no or order.shopify_order_id} (shopify_id={order.shopify_order_id})")
    
    # Check webhook events for this order
    events = WebhookEvent.objects.all()
    matching = []
    for event in events:
        try:
            if order.shopify_order_id in json.dumps(event.payload):
                matching.append(event)
        except:
            pass
    
    print(f"  Webhook events found: {len(matching)}")
    for event in matching[:3]:
        print(f"    - {event.topic} (processed: {event.processed_at})")
