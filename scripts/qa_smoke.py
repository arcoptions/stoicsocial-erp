from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import django

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

from core.models import Invoice, Order, PrintJob


@dataclass(frozen=True)
class RouteCheck:
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    follow: bool = True


def _runner_user() -> object:
    """Return an admin-like user for smoke testing endpoints behind auth."""
    user_model = get_user_model()
    user = user_model.objects.filter(is_superuser=True).order_by("id").first()
    if user is not None:
        return user

    # Fallback if no superuser exists in a local QA DB.
    user, _ = user_model.objects.get_or_create(
        username="qa_runner",
        defaults={
            "is_staff": True,
            "is_superuser": True,
            "email": "qa.runner@example.com",
        },
    )
    if hasattr(user, "set_unusable_password"):
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _build_checks() -> list[RouteCheck]:
    """Build a practical smoke probe set over inventory/admin/finance flows."""
    checks: list[RouteCheck] = [
        RouteCheck("/"),
        RouteCheck("/ops/inventory/orders/"),
        RouteCheck("/ops/orders/"),
        RouteCheck("/ops/inventory/print-batches/"),
        RouteCheck("/ops/print-batches/"),
        RouteCheck("/ops/inventory/receive/"),
        RouteCheck("/ops/inventory/forecast/"),
        RouteCheck("/ops/inventory/adjust/"),
        RouteCheck("/ops/inventory/audit-log/"),
        RouteCheck("/ops/sales/"),
        RouteCheck("/ops/finance/"),
        RouteCheck("/ops/finance/expenses/"),
        RouteCheck("/ops/finance/reconciliation/"),
        RouteCheck("/ops/finance/invoices/"),
        RouteCheck("/admin/"),
        RouteCheck("/admin/core/printjob/"),
        RouteCheck("/admin/core/order/"),
    ]

    order = Order.objects.order_by("-created_at").first()
    if order is not None:
        checks.append(RouteCheck(f"/ops/inventory/orders/{order.id}/"))

    job = PrintJob.objects.order_by("-created_at").first()
    if job is not None:
        checks.append(RouteCheck(f"/ops/inventory/print-batches/pick-list/{job.id}/"))

    invoice = Invoice.objects.order_by("-created_at").first()
    if invoice is not None:
        checks.append(RouteCheck(f"/ops/finance/invoices/{invoice.id}/"))

    return checks


def main() -> int:
    """Execute smoke probes and print a concise pass/fail summary."""
    client = Client()
    client.force_login(_runner_user())

    checks = _build_checks()
    failures: list[str] = []

    logo_path = REPO_ROOT / "core" / "static" / "branding" / "bi-logo-mono.svg"
    if logo_path.exists():
        print(f"[OK] logo file {logo_path}")
    else:
        print(f"[FAIL] logo file missing: {logo_path}")
        failures.append(f"missing logo file: {logo_path}")

    print("Running smoke checks...")
    for check in checks:
        response = client.get(check.path, SERVER_NAME="localhost", follow=check.follow)
        ok = response.status_code in check.expected_statuses
        marker = "OK" if ok else "FAIL"
        print(f"[{marker}] {response.status_code} {check.path}")
        if not ok:
            failures.append(f"{response.status_code} {check.path}")

    logout_response = client.post("/accounts/logout/", SERVER_NAME="localhost", follow=False)
    logout_ok = logout_response.status_code in (302, 303)
    print(f"[{'OK' if logout_ok else 'FAIL'}] {logout_response.status_code} /accounts/logout/ (POST)")
    if not logout_ok:
        failures.append(f"{logout_response.status_code} /accounts/logout/ (POST)")

    if failures:
        print("\nSmoke checks failed:")
        for row in failures:
            print(f" - {row}")
        return 1

    print("\nSmoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
