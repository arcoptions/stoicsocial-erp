#!/usr/bin/env python
"""
Create cloud users for testing BoldERP.
Run with: railway run python setup_cloud_users.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User, Group, Permission

# ---------------------------------------------------------------------------
# 1. Ensure groups exist
# ---------------------------------------------------------------------------
groups_to_create = ["Inventory Manager", "Sales Manager", "Accountant", "Finance Manager", "Admin"]
for group_name in groups_to_create:
    Group.objects.get_or_create(name=group_name)
    print(f"  Group: {group_name}")

# ---------------------------------------------------------------------------
# 2. Create / update users
# ---------------------------------------------------------------------------
users = [
    {
        "username": "ARC",
        "password": "ARC@BoldERP2026!",
        "email": "arc@stoicsocial.in",
        "is_superuser": True,
        "is_staff": True,
        "groups": [],
        "role": "Superuser / Full Admin",
    },
    {
        "username": "testim",
        "password": "Testim@Inv2026!",
        "email": "testim@stoicsocial.in",
        "is_superuser": False,
        "is_staff": False,
        "groups": ["Inventory Manager"],
        "role": "Inventory Manager",
    },
    {
        "username": "testsales",
        "password": "TestSales@2026!",
        "email": "testsales@stoicsocial.in",
        "is_superuser": False,
        "is_staff": False,
        "groups": ["Sales Manager"],
        "role": "Sales Manager",
    },
    {
        "username": "testfin",
        "password": "TestFin@2026!",
        "email": "testfin@stoicsocial.in",
        "is_superuser": False,
        "is_staff": False,
        "groups": ["Accountant", "Finance Manager"],
        "role": "Finance / Accountant",
    },
]

print("\n" + "=" * 60)
print("CREATING USERS")
print("=" * 60)

for u in users:
    user, created = User.objects.update_or_create(
        username=u["username"],
        defaults={
            "email": u["email"],
            "is_superuser": u["is_superuser"],
            "is_staff": u["is_staff"],
        },
    )
    user.set_password(u["password"])
    user.save()

    user.groups.clear()
    for group_name in u["groups"]:
        group = Group.objects.get(name=group_name)
        user.groups.add(group)

    status = "CREATED" if created else "UPDATED"
    print(f"\n[{status}] {u['username']}")
    print(f"  Role     : {u['role']}")
    print(f"  Password : {u['password']}")
    print(f"  Groups   : {u['groups'] or ['superuser - all access']}")

print("\n" + "=" * 60)
print("ALL USERS READY")
print("=" * 60)
print("\nLogin URL: https://stoicsocial-web-production.up.railway.app/accounts/login/")
print("Admin URL: https://stoicsocial-web-production.up.railway.app/admin/")
