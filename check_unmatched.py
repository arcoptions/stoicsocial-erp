#!/usr/bin/env python
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import OrderLine
from collections import Counter

unmatched = OrderLine.objects.filter(printed_sku__isnull=True)
print(f'Total unmatched lines: {unmatched.count()}\n')

products = Counter([line.product_name for line in unmatched])
print('Unmatched by product:')
for product, count in sorted(products.items()):
    print(f'  {product}: {count}')
