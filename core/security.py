"""Authentication and authorization decorators for BoldERP."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse

ADMIN_GROUPS = {"Admin"}
INVENTORY_GROUPS = {"Inventory Manager"}
FINANCE_GROUPS = {"Accountant", "Finance Manager"}
SALES_GROUPS = {"Sales Manager"}


def _group_names(user: Any) -> set[str]:
    """Return the authenticated user's group names as a set."""
    if not getattr(user, "is_authenticated", False):
        return set()
    groups = getattr(user, "groups", None)
    if groups is None:
        return set()
    return set(groups.values_list("name", flat=True))


def is_admin_user(user: Any) -> bool:
    """Return True when the user has unrestricted ERP admin access."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return bool(_group_names(user) & ADMIN_GROUPS)


def has_inventory_access(user: Any) -> bool:
    """Return True for users who can access inventory management pages."""
    return is_admin_user(user) or bool(_group_names(user) & INVENTORY_GROUPS)


def has_finance_access(user: Any) -> bool:
    """Return True for users who can access finance management pages."""
    return is_admin_user(user) or bool(_group_names(user) & FINANCE_GROUPS)


def has_sales_access(user: Any) -> bool:
    """Return True for users who can access sales management pages."""
    return is_admin_user(user) or bool(_group_names(user) & SALES_GROUPS)


def _access_required(
    access_check: Callable[[Any], bool],
    denied_message: str,
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """Create a view decorator enforcing a domain-specific access check."""

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            if not access_check(request.user):
                raise PermissionDenied(denied_message)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


inventory_access_required = _access_required(
    has_inventory_access,
    "Inventory access is required for this page.",
)
finance_access_required = _access_required(
    has_finance_access,
    "Finance access is required for this page.",
)
sales_access_required = _access_required(
    has_sales_access,
    "Sales access is required for this page.",
)


def role_context(request: HttpRequest) -> dict[str, bool]:
    """Expose module access flags for navigation and template-level controls."""
    user = request.user
    return {
        "can_admin": is_admin_user(user),
        "can_inventory": has_inventory_access(user),
        "can_finance": has_finance_access(user),
        "can_sales": has_sales_access(user),
    }


def internal_token_required(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Require a valid X-Internal-Token header for machine-to-machine API endpoints.

    The token is validated against settings.INTERNAL_API_TOKEN if configured.
    Returns 401 Unauthorized if the token is missing or invalid.
    """

    @wraps(view_func)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        internal_token = getattr(settings, "INTERNAL_API_TOKEN", "")
        if not internal_token:
            return JsonResponse({"detail": "Internal API token not configured"}, status=500)

        provided_token = request.headers.get("X-Internal-Token", "").strip()
        if not provided_token or provided_token != internal_token:
            return JsonResponse({"detail": "Invalid or missing X-Internal-Token header"}, status=401)

        return view_func(request, *args, **kwargs)

    return wrapper
