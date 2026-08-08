from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import BlankSKU, Design, PrintJob, PrintedSKU, Vendor
from core.views.print_batch import SuggestedBatchRow


class ConfirmPrintBatchTests(TestCase):
    def test_rejects_cumulative_shortfall_for_shared_blank_sku(self) -> None:
        user = get_user_model().objects.create_superuser(username="inventory-admin", password="test-password")
        vendor = Vendor.objects.create(name="Test Vendor")
        blank_sku = BlankSKU.objects.create(fabric="180 GSM", colour="Black", size="M", on_hand=10)
        first_design = Design.objects.create(name="First Design")
        second_design = Design.objects.create(name="Second Design")
        first_printed_sku = PrintedSKU.objects.create(
            design=first_design,
            colour="Black",
            size="M",
            blank_sku=blank_sku,
        )
        second_printed_sku = PrintedSKU.objects.create(
            design=second_design,
            colour="Black",
            size="M",
            blank_sku=blank_sku,
        )
        rows = [
            SuggestedBatchRow(first_printed_sku, blank_sku, 6, 0, 6, 10, 0),
            SuggestedBatchRow(second_printed_sku, blank_sku, 6, 0, 6, 10, 0),
        ]
        self.client.force_login(user)

        with patch("core.views.print_batch._build_suggested_rows", return_value=rows):
            response = self.client.post(
                reverse("print-batch-confirm"),
                {
                    "vendor_id": str(vendor.id),
                    f"qty_{first_printed_sku.id}": "6",
                    f"qty_{second_printed_sku.id}": "6",
                },
            )

        self.assertRedirects(response, reverse("print-batch-suggest"), fetch_redirect_response=False)
        self.assertFalse(PrintJob.objects.exists())
        blank_sku.refresh_from_db()
        self.assertEqual(blank_sku.on_hand, 10)