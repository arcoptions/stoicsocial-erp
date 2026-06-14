"""Check schema consistency after migration."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from core.models import DesignAsset, DesignAssetFile, PrintedSKU


class Command(BaseCommand):
    help = "Validate schema consistency after refactor migration"

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write("\n🔍 Checking schema consistency...\n")

        errors = []
        warnings = []

        # 1. Check PrintedSKU references
        self.stdout.write("1️⃣  Checking PrintedSKU references...")
        printedskus_without_asset = PrintedSKU.objects.filter(design_asset__isnull=True).count()
        printedskus_without_blank = PrintedSKU.objects.filter(blank_sku__isnull=True).count()

        if printedskus_without_asset > 0:
            warnings.append(f"  {printedskus_without_asset} PrintedSKUs without design_asset (expected during migration)")
        if printedskus_without_blank > 0:
            warnings.append(f"  {printedskus_without_blank} PrintedSKUs without blank_sku")

        # 2. Check DesignAsset linking
        self.stdout.write("2️⃣  Checking DesignAsset.blank_sku...")
        design_assets_unlinked = DesignAsset.objects.filter(blank_sku__isnull=True).count()
        if design_assets_unlinked > 0:
            warnings.append(f"  {design_assets_unlinked} DesignAssets without blank_sku (should be populated)")

        # 3. Check for orphaned files
        self.stdout.write("3️⃣  Checking DesignAssetFiles...")
        try:
            orphaned_files = DesignAssetFile.objects.filter(design_asset__isnull=True).count()
            if orphaned_files > 0:
                errors.append(f"  {orphaned_files} orphaned DesignAssetFiles (design_asset is NULL)")
        except Exception as e:
            errors.append(f"  Error checking files: {str(e)}")

        # 4. Check test data flags
        self.stdout.write("4️⃣  Checking test data flags...")
        test_orders = PrintedSKU.objects.filter(is_test_data__isnull=True).count()
        if test_orders > 0:
            warnings.append(f"  {test_orders} PrintedSKUs with NULL is_test_data (should be True or False)")

        # 5. Check data integrity
        self.stdout.write("5️⃣  Checking data integrity...")
        design_assets_total = DesignAsset.objects.count()
        design_assets_linked = DesignAsset.objects.filter(blank_sku__isnull=False).count()

        self.stdout.write(f"  Total DesignAssets: {design_assets_total}")
        self.stdout.write(f"  Linked with blank_sku: {design_assets_linked}")
        self.stdout.write(f"  Coverage: {design_assets_linked}/{design_assets_total} ({design_assets_linked*100//max(design_assets_total,1)}%)")

        # Print results
        if errors:
            self.stdout.write(self.style.ERROR(f"\n❌ {len(errors)} ERRORS:"))
            for error in errors:
                self.stdout.write(self.style.ERROR(error))

        if warnings:
            self.stdout.write(self.style.WARNING(f"\n⚠️  {len(warnings)} WARNINGS:"))
            for warning in warnings:
                self.stdout.write(self.style.WARNING(warning))

        if not errors and not warnings:
            self.stdout.write(self.style.SUCCESS("\n✅ All consistency checks passed!"))
        elif not errors:
            self.stdout.write(self.style.SUCCESS("\n✅ No critical errors (warnings are expected during migration)"))
        else:
            self.stdout.write(self.style.ERROR("\n❌ Critical errors found. Please resolve before production."))
