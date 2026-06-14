"""Populate DesignAsset.blank_sku from existing PrintedSKU links."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from core.models import DesignAsset, PrintedSKU


class Command(BaseCommand):
    help = "Populate DesignAsset.blank_sku from existing PrintedSKU blank_sku links"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--production",
            action="store_true",
            help="Confirm for production rollout",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        production = options["production"]

        if production and not dry_run:
            response = input("⚠️  This is for PRODUCTION. Proceed? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                self.stdout.write(self.style.WARNING("Cancelled"))
                return

        self.stdout.write("\n📊 Analyzing PrintedSKU → DesignAsset.blank_sku links...\n")

        # Group PrintedSKU by design_asset to find most common blank_sku
        design_asset_blanks = {}
        conflicts = []

        for sku in PrintedSKU.objects.filter(blank_sku__isnull=False).select_related(
            "design", "blank_sku"
        ).iterator(chunk_size=1000):
            # Find or create design asset for this sku's design + colour
            asset_key = (sku.design_id, sku.colour)

            if asset_key not in design_asset_blanks:
                design_asset_blanks[asset_key] = {}

            blank_sku_id = sku.blank_sku_id
            if blank_sku_id not in design_asset_blanks[asset_key]:
                design_asset_blanks[asset_key][blank_sku_id] = 0
            design_asset_blanks[asset_key][blank_sku_id] += 1

        # Find the most common blank_sku for each design_asset
        assignments = {}
        for asset_key, blank_skus in design_asset_blanks.items():
            if len(blank_skus) > 1:
                # Multiple different blank_skus for same design+colour
                most_common = max(blank_skus.items(), key=lambda x: x[1])
                assignments[asset_key] = most_common[0]
                conflicts.append((asset_key, blank_skus))
            else:
                # Single blank_sku for this design+colour
                assignments[asset_key] = list(blank_skus.keys())[0]

        # Apply updates
        updated_count = 0
        error_count = 0

        for (design_id, colour), blank_sku_id in assignments.items():
            try:
                asset = DesignAsset.objects.get(design_id=design_id, colour=colour)

                if dry_run:
                    old_blank = asset.blank_sku_id
                    status = "UPDATE" if old_blank else "SET"
                    self.stdout.write(f"  {status}: {asset} → blank_sku_id={blank_sku_id}")
                else:
                    asset.blank_sku_id = blank_sku_id
                    asset.save(update_fields=["blank_sku_id"])
                    self.stdout.write(self.style.SUCCESS(f"  ✅ {asset}"))

                updated_count += 1
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f"  ❌ {design_id}/{colour}: {str(e)}"))

        # Report conflicts
        if conflicts:
            self.stdout.write(self.style.WARNING(f"\n⚠️  Found {len(conflicts)} design+colour with multiple blank SKUs:"))
            for (design_id, colour), blank_skus in conflicts[:5]:
                self.stdout.write(f"  - Design {design_id}, Colour '{colour}':")
                for blank_sku_id, count in blank_skus.items():
                    self.stdout.write(f"      blank_sku_id={blank_sku_id}: {count} PrintedSKUs")
            if len(conflicts) > 5:
                self.stdout.write(f"  ... and {len(conflicts) - 5} more")

        # Summary
        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"\n✅ {verb} {updated_count} DesignAssets"))
        if error_count:
            self.stdout.write(self.style.ERROR(f"❌ {error_count} errors"))

        if dry_run:
            self.stdout.write("\n💡 Run without --dry-run to apply changes")
