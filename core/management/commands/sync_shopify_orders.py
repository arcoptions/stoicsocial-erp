from __future__ import annotations

import os
from typing import Any

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.services.shopify import ingest_order


class Command(BaseCommand):
    help = "Backfill all Shopify orders into BoldERP Order and OrderLine tables."

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
            "--dry-run",
            action="store_true",
            help="Fetch and count only; do not write to DB.",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Fetch Shopify orders page-by-page and upsert them via ingest_order."""
        shop_domain: str = str(options["shop_domain"]).strip()
        access_token: str = str(options["access_token"]).strip()
        api_version: str = str(options["api_version"]).strip()
        limit: int = int(options["limit"])
        dry_run: bool = bool(options["dry_run"])

        if not shop_domain:
            raise CommandError("Missing shop domain. Provide --shop-domain or SHOPIFY_SHOP_DOMAIN.")
        if not access_token:
            raise CommandError("Missing access token. Provide --access-token or SHOPIFY_ADMIN_API_TOKEN.")
        if limit <= 0 or limit > 250:
            raise CommandError("--limit must be between 1 and 250.")

        base_url = f"https://{shop_domain}/admin/api/{api_version}/orders.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

        params: dict[str, Any] = {
            "status": "any",
            "limit": limit,
            "order": "created_at asc",
            "fields": ",".join(
                [
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
            ),
        }

        total_fetched = 0
        total_upserted = 0
        next_url: str | None = None

        while True:
            response = requests.get(next_url or base_url, headers=headers, params=None if next_url else params, timeout=60)
            if response.status_code >= 400:
                raise CommandError(f"Shopify API error {response.status_code}: {response.text[:500]}")

            payload = response.json()
            orders = payload.get("orders", [])
            batch_count = len(orders)
            total_fetched += batch_count

            self.stdout.write(f"Fetched batch: {batch_count} orders (total={total_fetched})")

            if not dry_run:
                for order in orders:
                    ingest_order(order)
                    total_upserted += 1

            link_header = response.headers.get("Link", "")
            next_url = self._extract_next_link(link_header)
            if not next_url:
                break

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry-run complete. Orders fetched: {total_fetched}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Sync complete. Orders fetched: {total_fetched}, upserted: {total_upserted}"))

    def _extract_next_link(self, link_header: str) -> str | None:
        """Return the URL for rel=next from Shopify Link header."""
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
