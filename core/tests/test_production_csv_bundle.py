import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from core.models import Vendor


class ProductionCsvBundleTests(TestCase):
    @staticmethod
    def _write_bundle(bundle_dir: Path, *, vendor_rows: list[dict[str, str]] | None = None) -> None:
        headers = {
            "designs.csv": ["design_name", "colour"],
            "blank_skus.csv": ["fabric", "colour", "size", "on_hand"],
            "printed_skus.csv": ["design_name", "colour", "size"],
            "vendors.csv": ["name", "contact", "is_active"],
        }
        for filename, fieldnames in headers.items():
            with (bundle_dir / filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                if filename == "vendors.csv":
                    writer.writerows(vendor_rows or [])

    def test_dry_run_does_not_require_orders_csv(self) -> None:
        with TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            self._write_bundle(bundle_dir)

            call_command(
                "import_production_csv_bundle",
                "--dir",
                str(bundle_dir),
                "--dry-run",
            )

    def test_imports_optional_vendor_file(self) -> None:
        with TemporaryDirectory() as directory:
            bundle_dir = Path(directory)
            self._write_bundle(
                bundle_dir,
                vendor_rows=[{"name": "Knitwear", "contact": "ops@example.com", "is_active": "true"}],
            )

            call_command("import_production_csv_bundle", "--dir", str(bundle_dir))

        vendor = Vendor.objects.get(name="Knitwear")
        self.assertEqual(vendor.contact, "ops@example.com")
        self.assertTrue(vendor.is_active)
