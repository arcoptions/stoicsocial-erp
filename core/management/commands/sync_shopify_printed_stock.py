from __future__ import annotations

import os
from typing import Any

import requests
from django.core.management.base import BaseCommand, CommandError

from core.models import Design, PrintedSKU

SIZE_TOKENS = {"XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL"}
SHOPIFY_POLICY_VALUES = {"continue", "deny"}


def _clean(value: Any) -> str:
    """Return trimmed string form for Shopify payload values."""
    return str(value or "").strip()


def _normalize_size(value: str | None) -> str | None:
    """Normalize size labels to canonical tokens used in PrintedSKU rows."""
    raw = _clean(value).upper()
    if not raw:
        return None
    if raw == "XXL":
        return "2XL"
    return raw if raw in SIZE_TOKENS else None


def _normalize_variant(value: str | None) -> str | None:
    """Return canonical variant text or None for empty/default labels."""
    cleaned = _clean(value)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in {"default", "default title", "na", "n/a", "none"}:
        return None
    return cleaned


def _normalize_colour(value: str | None) -> str:
    """Return canonical colour, never using Shopify inventory policy strings as colours."""
    cleaned = _clean(value)
    if not cleaned:
        return "Unknown"
    if cleaned.lower() in SHOPIFY_POLICY_VALUES:
        return "Unknown"
    return cleaned


def _extract_variant_colour_size(product: dict[str, Any], variant: dict[str, Any]) -> tuple[str | None, str, str | None]:
    """Extract variant label, colour, and size from Shopify product+variant options."""
    options = product.get("options", [])
    option_names: list[str] = []
    for option in options:
        option_names.append(_clean(option.get("name")).lower())

    values = [
        _clean(variant.get("option1")),
        _clean(variant.get("option2")),
        _clean(variant.get("option3")),
    ]

    colour = ""
    size: str | None = None
    variant_parts: list[str] = []

    for idx, value in enumerate(values):
        if not value:
            continue
        option_name = option_names[idx] if idx < len(option_names) else ""
        normalized_size = _normalize_size(value)

        if "color" in option_name or "colour" in option_name:
            colour = value
            continue
        if "size" in option_name:
            size = normalized_size or value.upper()
            continue
        if normalized_size and size is None:
            size = normalized_size
            continue
        variant_parts.append(value)

    # Only use variant.title as a fallback when options didn't already capture size.
    # If size is already set (from a "Size" option), the title is just the rendered
    # option values joined – appending it to variant_parts would duplicate size as variant.
    if size is None and not variant_parts:
        title = _clean(variant.get("title"))
        if title and title.lower() not in {"default title", "default"}:
            size_candidate = _normalize_size(title)
            if size_candidate:
                size = size_candidate
            else:
                variant_parts.append(title)

    # Handle single-option products where the only option is size.
    if not variant_parts and size is not None:
        variant_label = None
    else:
        variant_label = " / ".join(part for part in variant_parts if part) or None

    if variant_label and size is None:
        moved_size = _normalize_size(variant_label)
        if moved_size is not None:
            size = moved_size
            variant_label = None

    return _normalize_variant(variant_label), _normalize_colour(colour), size


def _cleanup_legacy_bad_rows(stdout: Any) -> tuple[int, int, int]:
    """Normalize legacy malformed rows and merge safe duplicates created by old sync logic."""
    normalized = 0
    merged = 0
    skipped_merge_with_refs = 0

    malformed_qs = PrintedSKU.objects.filter(
        size__isnull=True,
        variant__isnull=False,
    )

    for sku in malformed_qs:
        candidate_size = _normalize_size(sku.variant)
        if candidate_size is None:
            continue

        canonical_colour = _normalize_colour(sku.colour)
        target = (
            PrintedSKU.objects
            .filter(
                design=sku.design,
                variant__isnull=True,
                colour=canonical_colour,
                size=candidate_size,
            )
            .exclude(id=sku.id)
            .first()
        )

        if target is not None:
            has_refs = (
                sku.order_lines.exists()
                or sku.bundle_components.exists()
                or sku.print_job_lines.exists()
                or sku.movements.exists()
                or sku.reprint_tasks.exists()
            )
            if has_refs:
                skipped_merge_with_refs += 1
                continue
            target.is_active = target.is_active or sku.is_active
            target.save(update_fields=["is_active", "updated_at"])
            sku.delete()
            merged += 1
            continue

        update_fields: list[str] = []
        if sku.variant is not None:
            sku.variant = None
            update_fields.append("variant")
        if sku.size != candidate_size:
            sku.size = candidate_size
            update_fields.append("size")
        if sku.colour != canonical_colour:
            sku.colour = canonical_colour
            update_fields.append("colour")

        if update_fields:
            update_fields.append("updated_at")
            sku.save(update_fields=update_fields)
            normalized += 1

    if normalized or merged or skipped_merge_with_refs:
        stdout.write(
            f"Legacy cleanup: normalized={normalized}, merged={merged}, skipped_with_refs={skipped_merge_with_refs}."
        )
    return normalized, merged, skipped_merge_with_refs


def _extract_next_link(link_header: str) -> str | None:
    """Return Shopify REST next-page URL from Link header."""
    if not link_header:
        return None
    for part in [chunk.strip() for chunk in link_header.split(",") if chunk.strip()]:
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1 and end > start:
                return part[start + 1 : end]
    return None


class Command(BaseCommand):
    help = "Sync PrintedSKU names/variants from Shopify products without changing stock levels."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--shop-domain",
            default=os.getenv("SHOPIFY_SHOP_DOMAIN", ""),
            help="Shop domain (or SHOPIFY_SHOP_DOMAIN), e.g. mystore.myshopify.com",
        )
        parser.add_argument(
            "--access-token",
            default=os.getenv("SHOPIFY_ADMIN_API_TOKEN", ""),
            help="Shopify Admin API token (or SHOPIFY_ADMIN_API_TOKEN)",
        )
        parser.add_argument(
            "--api-version",
            default=os.getenv("SHOPIFY_API_VERSION", "2025-01"),
            help="Shopify Admin API version",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=250,
            help="Products page size (max 250)",
        )
        parser.add_argument(
            "--archive-missing",
            action="store_true",
            help="Archive active PrintedSKU rows that were not found in Shopify during this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and parse only; do not write DB changes.",
        )
        parser.add_argument(
            "--skip-legacy-cleanup",
            action="store_true",
            help="Skip cleanup of malformed legacy printed rows created by earlier sync versions.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Fetch Shopify products+variants and upsert PrintedSKU identity rows only."""
        shop_domain = _clean(options["shop_domain"])
        access_token = _clean(options["access_token"])
        api_version = _clean(options["api_version"])
        limit = int(options["limit"])
        archive_missing = bool(options["archive_missing"])
        dry_run = bool(options["dry_run"])
        skip_legacy_cleanup = bool(options["skip_legacy_cleanup"])

        if not shop_domain:
            raise CommandError("Missing shop domain. Provide --shop-domain or SHOPIFY_SHOP_DOMAIN.")
        if not access_token:
            raise CommandError("Missing access token. Provide --access-token or SHOPIFY_ADMIN_API_TOKEN.")
        if limit < 1 or limit > 250:
            raise CommandError("--limit must be between 1 and 250.")

        base_url = f"https://{shop_domain}/admin/api/{api_version}/products.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        params: dict[str, Any] = {
            "status": "active",
            "limit": limit,
            "fields": "id,title,variants,options,status",
        }

        fetched_products = 0
        parsed_variants = 0
        created = 0
        updated = 0
        seen_ids: set[str] = set()

        next_url: str | None = None
        while True:
            response = requests.get(next_url or base_url, headers=headers, params=None if next_url else params, timeout=60)
            if response.status_code >= 400:
                raise CommandError(f"Shopify API error {response.status_code}: {response.text[:500]}")

            payload = response.json()
            products = payload.get("products", [])
            fetched_products += len(products)
            self.stdout.write(f"Fetched products batch: {len(products)} (total={fetched_products})")

            for product in products:
                design_name = _clean(product.get("title"))
                if not design_name:
                    continue
                options = product.get("options", [])
                option_names = [_clean(opt.get("name")) for opt in options if _clean(opt.get("name"))]
                has_variants = len(option_names) > 0

                if dry_run:
                    design = None
                else:
                    design, _ = Design.objects.get_or_create(
                        name=design_name,
                        defaults={
                            "has_variants": has_variants,
                            "variants": option_names,
                        },
                    )
                    design.has_variants = has_variants
                    design.variants = option_names
                    design.save(update_fields=["has_variants", "variants", "updated_at"])

                for variant in product.get("variants", []):
                    parsed_variants += 1
                    variant_label, colour, size = _extract_variant_colour_size(product, variant)

                    if dry_run:
                        continue

                    sku, was_created = PrintedSKU.objects.get_or_create(
                        design=design,
                        variant=variant_label,
                        colour=colour,
                        size=size,
                        defaults={"is_active": True},
                    )
                    if was_created:
                        created += 1
                    else:
                        if not sku.is_active:
                            sku.is_active = True
                            sku.save(update_fields=["is_active", "updated_at"])
                        updated += 1
                    seen_ids.add(str(sku.id))

            next_url = _extract_next_link(response.headers.get("Link", ""))
            if not next_url:
                break

        archived = 0
        normalized = 0
        merged = 0
        skipped_merge_with_refs = 0
        if not dry_run and archive_missing:
            to_archive = PrintedSKU.objects.filter(is_active=True).exclude(id__in=seen_ids)
            archived = to_archive.update(is_active=False, on_hand=0)

        if not dry_run and not skip_legacy_cleanup:
            normalized, merged, skipped_merge_with_refs = _cleanup_legacy_bad_rows(self.stdout)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry-run complete. Products={fetched_products}, variants parsed={parsed_variants}."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Printed stock sync complete. "
                f"Products={fetched_products}, variants={parsed_variants}, "
                f"created={created}, updated={updated}, archived={archived}, "
                f"legacy_normalized={normalized}, legacy_merged={merged}, legacy_skipped_with_refs={skipped_merge_with_refs}."
            )
        )
