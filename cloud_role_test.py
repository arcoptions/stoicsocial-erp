import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth.models import User
from django.test import Client

users = ["ARC", "testim", "testsales", "testfin"]
print("USERS:")
for u in User.objects.filter(username__in=users).order_by("username"):
    print(u.username, u.is_superuser, list(u.groups.values_list("name", flat=True)))

creds = {
    "ARC": "ARC@BoldERP2026!",
    "testim": "Testim@Inv2026!",
    "testsales": "TestSales@2026!",
    "testfin": "TestFin@2026!",
}

paths = [
    "/ops/inventory/orders/",
    "/ops/sales/",
    "/ops/finance/",
    "/admin/",
]

host = "stoicsocial-web-production.up.railway.app"

print("\nACCESS MATRIX:")
for username, password in creds.items():
    client = Client()
    ok = client.login(username=username, password=password)
    print(f"\n{username} login={ok}")
    for path in paths:
        response = client.get(path, HTTP_HOST=host)
        print(f"  {path} -> {response.status_code}")
