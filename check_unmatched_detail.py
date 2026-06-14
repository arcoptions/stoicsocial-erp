#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import OrderLine

unmatched = OrderLine.objects.filter(printed_sku__isnull=True)
print(f'Remaining {unmatched.count()} unmatched lines:\n')

for line in unmatched:
    print(f'{line.product_name} / {line.size} (qty {line.quantity})')
