from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, Callable

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Order
from core.services.shopify import ingest_order


ORDER_FIELDS = [
    "id",
    "name",
    "email",
    "customer",
    "tags",
    "line_items",
    "fulfillment_status",
    "created_at",
    "updated_at",
    "cancelled_at",
    "cancel_reason",
]


def extract_next_link(link_header: str) -> str | None:
    """Return the URL for rel=next from a Shopify Link header."""
    if not link_header:
        return None

    parts = [part.strip() for part in link_header.split(",") if part.strip()]
    for part in parts:
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1 and end > start:
                return part[start + 1 : end]
    return None


def sync_orders(
    *,
    shop_domain: str,
    access_token: str,
    api_version: str = "2025-01",
    limit: int = 250,
    updated_at_min: str | None = None,
    apply_inventory: bool = False,
    dry_run: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Pull orders from the Shopify Admin API and upsert them, returning per-outcome counts.

    Without ``updated_at_min`` this walks the entire order history. With it, only orders
    Shopify touched since that timestamp come back, which is what makes a periodic catch-up
    cheap enough to run every few minutes.
    """
    shop_domain = str(shop_domain or "").strip()
    access_token = str(access_token or "").strip()
    api_version = str(api_version or "").strip() or "2025-01"

    if not shop_domain:
        raise ValueError("Missing shop domain. Provide --shop-domain or SHOPIFY_SHOP_DOMAIN.")
    if not access_token:
        raise ValueError("Missing access token. Provide --access-token or SHOPIFY_ADMIN_API_TOKEN.")
    if limit <= 0 or limit > 250:
        raise ValueError("limit must be between 1 and 250.")

    base_url = f"https://{shop_domain}/admin/api/{api_version}/orders.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    params: dict[str, Any] = {
        "status": "any",
        "limit": limit,
        "order": "created_at asc",
        "fields": ",".join(ORDER_FIELDS),
    }
    if updated_at_min:
        params["updated_at_min"] = updated_at_min

    counts = {"fetched": 0, "created": 0, "updated": 0}
    next_url: str | None = None

    while True:
        response = requests.get(
            next_url or base_url,
            headers=headers,
            params=None if next_url else params,
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Shopify API error {response.status_code}: {response.text[:500]}")

        orders = response.json().get("orders", [])
        counts["fetched"] += len(orders)
        if on_progress is not None:
            on_progress(f"Fetched batch: {len(orders)} orders (total={counts['fetched']})")

        if not dry_run and orders:
            incoming_ids = [str(order.get("id") or "").strip() for order in orders]
            already_known = set(
                Order.objects.filter(shopify_order_id__in=[i for i in incoming_ids if i]).values_list(
                    "shopify_order_id", flat=True
                )
            )
            for order in orders:
                is_update = str(order.get("id") or "").strip() in already_known
                ingest_order(order, apply_inventory_side_effects=apply_inventory)
                counts["updated" if is_update else "created"] += 1

        next_url = extract_next_link(response.headers.get("Link", ""))
        if not next_url:
            break

    return counts


class Command(BaseCommand):
    help = "Backfill or catch up Shopify orders into BoldERP Order and OrderLine tables."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--shop-domain",
            default=os.getenv("SHOPIFY_SHOP_DOMAIN", ""),
            help="Shop domain, e.g. mystore.myshopify.com (or set SHOPIFY_SHOP_DOMAIN).",
        )
        parser.add_argument(
            "--access-token",
            default=os.getenv("SHOPIFY_ADMIN_API_TOKEN", ""),
            help="Shopify Admin API access token (or set SHOPIFY_ADMIN_API_TOKEN).",
        )
        parser.add_argument(
            "--api-version",
            default=os.getenv("SHOPIFY_API_VERSION", "2025-01"),
            help="Shopify Admin API version.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=250,
            help="Page size (max 250).",
        )
        parser.add_argument(
            "--since-minutes",
            type=int,
            default=None,
            help="Only fetch orders Shopify updated in the last N minutes (catch-up mode).",
        )
        parser.add_argument(
            "--updated-at-min",
            default=None,
            help="Only fetch orders updated at or after this ISO-8601 timestamp. Overrides --since-minutes.",
        )
        parser.add_argument(
            "--apply-inventory",
            action="store_true",
            help="Apply inventory side effects (reserve printed stock) as a live webhook would. "
            "Leave off for a full historical backfill.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and count only; do not write to DB.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Fetch Shopify orders page-by-page and upsert them via ingest_order."""
        updated_at_min: str | None = options["updated_at_min"]
        since_minutes: int | None = options["since_minutes"]
        if not updated_at_min and since_minutes:
            if since_minutes <= 0:
                raise CommandError("--since-minutes must be positive.")
            updated_at_min = (timezone.now() - timedelta(minutes=since_minutes)).isoformat()

        try:
            counts = sync_orders(
                shop_domain=options["shop_domain"],
                access_token=options["access_token"],
                api_version=options["api_version"],
                limit=int(options["limit"]),
                updated_at_min=updated_at_min,
                apply_inventory=bool(options["apply_inventory"]),
                dry_run=bool(options["dry_run"]),
                on_progress=self.stdout.write,
            )
        except (ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc

        window = f" since {updated_at_min}" if updated_at_min else ""
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"Dry-run complete{window}. Orders fetched: {counts['fetched']}")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Sync complete{window}. Orders fetched: {counts['fetched']}, "
                    f"created: {counts['created']}, updated: {counts['updated']}"
                )
            )
