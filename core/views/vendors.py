from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.models import Vendor
from core.security import inventory_access_required, is_admin_user


@login_required
@inventory_access_required
def vendor_list(request: HttpRequest) -> HttpResponse:
    """List all vendors with inline create and toggle-active for admins."""
    if request.method == "POST":
        if not is_admin_user(request.user):
            messages.error(request, "Only admin users can manage vendors.")
            return redirect("vendor-list")

        action = request.POST.get("action", "").strip()

        if action == "create":
            name = request.POST.get("name", "").strip()
            contact = request.POST.get("contact", "").strip()
            if not name:
                messages.error(request, "Vendor name is required.")
                return redirect("vendor-list")
            _, created = Vendor.objects.get_or_create(
                name=name,
                defaults={"contact": contact, "is_active": True},
            )
            if created:
                messages.success(request, f"Vendor '{name}' created.")
            else:
                messages.warning(request, f"Vendor '{name}' already exists.")
            return redirect("vendor-list")

        if action == "toggle":
            vendor_id = request.POST.get("vendor_id", "").strip()
            vendor = Vendor.objects.filter(id=vendor_id).first()
            if vendor is None:
                messages.error(request, "Vendor not found.")
                return redirect("vendor-list")
            vendor.is_active = not vendor.is_active
            vendor.save(update_fields=["is_active", "updated_at"])
            state = "activated" if vendor.is_active else "deactivated"
            messages.success(request, f"Vendor '{vendor.name}' {state}.")
            return redirect("vendor-list")

        if action == "update":
            vendor_id = request.POST.get("vendor_id", "").strip()
            vendor = Vendor.objects.filter(id=vendor_id).first()
            if vendor is None:
                messages.error(request, "Vendor not found.")
                return redirect("vendor-list")
            name = request.POST.get("name", "").strip()
            contact = request.POST.get("contact", "").strip()
            if not name:
                messages.error(request, "Vendor name is required.")
                return redirect("vendor-list")
            vendor.name = name
            vendor.contact = contact
            vendor.save(update_fields=["name", "contact", "updated_at"])
            messages.success(request, f"Vendor '{name}' updated.")
            return redirect("vendor-list")

    vendors = Vendor.objects.order_by("-is_active", "name")
    return render(
        request,
        "core/vendor_list.html",
        {
            "vendors": vendors,
            "is_admin": is_admin_user(request.user),
        },
    )
