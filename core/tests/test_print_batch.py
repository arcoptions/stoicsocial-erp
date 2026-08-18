from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    BlankSKU,
    Design,
    Order,
    OrderLine,
    PrintJob,
    PrintedSKU,
    ProductNameAlias,
    Vendor,
)
from core.services.shopify import _resolve_printed_sku, ingest_order
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


class UnmatchedOrderRepairTests(TestCase):
    """The Print Batches page must be able to fix an unmatched row, not just report it."""

    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="repair-admin", password="test-password"
        )
        self.client.force_login(self.user)
        self.url = reverse("print-batch-suggest")
        self.order = ingest_order(
            {
                "id": "repair-order-1",
                "name": "#5001",
                "created_at": "2026-08-17T09:30:00Z",
                "line_items": [
                    {
                        "id": "repair-line-1",
                        "title": "Delulu with lots of kalalu",
                        "variant_title": "M",
                        "quantity": 2,
                    }
                ],
            },
            apply_inventory_side_effects=True,
        )
        self.line = self.order.lines.get()
        self.assertIsNone(self.line.printed_sku_id)

    def _post(self, **fields: str):
        payload = {
            "product_name": "Delulu with lots of kalalu",
            "variant": "",
            "size": "M",
            "remember": "1",
        }
        payload.update(fields)
        return self.client.post(self.url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_link_unmatched_reserves_stock_when_available(self) -> None:
        design = Design.objects.create(name="Delulu Corrected")
        sku = PrintedSKU.objects.create(design=design, colour="Black", size="M", on_hand=5)

        response = self._post(action="link_unmatched", printed_sku_id=str(sku.id))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.line.refresh_from_db()
        sku.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.line.printed_sku_id, sku.id)
        self.assertEqual(self.line.status, OrderLine.STATUS_READY_SHIP)
        self.assertEqual(sku.reserved, 2)
        self.assertEqual(self.order.status, Order.STATUS_READY_TO_SHIP)

    def test_link_unmatched_queues_for_printing_when_stock_is_short(self) -> None:
        design = Design.objects.create(name="Delulu Corrected")
        sku = PrintedSKU.objects.create(design=design, colour="Black", size="M", on_hand=0)

        self._post(action="link_unmatched", printed_sku_id=str(sku.id))

        self.line.refresh_from_db()
        sku.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.line.status, OrderLine.STATUS_TO_BE_PRINTED)
        self.assertEqual(sku.reserved, 0)
        self.assertEqual(self.order.status, Order.STATUS_NEEDS_PRINTING)

    def test_link_unmatched_uses_the_sibling_sku_for_the_ordered_size(self) -> None:
        design = Design.objects.create(name="Delulu Corrected")
        # The operator picks the family via its L SKU; the M the customer ordered doesn't exist yet.
        template = PrintedSKU.objects.create(design=design, colour="Black", size="L", on_hand=9)

        self._post(action="link_unmatched", printed_sku_id=str(template.id))

        self.line.refresh_from_db()
        template.refresh_from_db()
        self.assertEqual(self.line.printed_sku.size, "M")
        self.assertEqual(self.line.printed_sku.design, design)
        self.assertEqual(template.reserved, 0)

    def test_remembering_the_name_makes_future_orders_match(self) -> None:
        design = Design.objects.create(name="Delulu Corrected")
        sku = PrintedSKU.objects.create(design=design, colour="Black", size="M", on_hand=5)

        self._post(action="link_unmatched", printed_sku_id=str(sku.id))

        alias = ProductNameAlias.objects.get()
        self.assertEqual(alias.design, design)
        resolved = _resolve_printed_sku(
            {"id": "future-line-1", "title": "Delulu with lots of kalalu", "variant_title": "XL"}
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.design, design)
        self.assertEqual(resolved.size, "XL")

    def test_not_remembering_leaves_no_alias(self) -> None:
        sku = PrintedSKU.objects.create(
            design=Design.objects.create(name="Delulu Corrected"), colour="Black", size="M"
        )

        self._post(action="link_unmatched", printed_sku_id=str(sku.id), remember="0")

        self.assertFalse(ProductNameAlias.objects.exists())

    def test_create_unmatched_sku_creates_design_sku_and_links_the_lines(self) -> None:
        response = self._post(
            action="create_unmatched_sku",
            design_name="Delulu With Lots Of Kalalu",
            sku_variant="",
            colour="Black",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        design = Design.objects.get(name="Delulu With Lots Of Kalalu")
        sku = PrintedSKU.objects.get(design=design, colour="Black", size="M")
        self.line.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.line.printed_sku_id, sku.id)
        self.assertEqual(self.line.status, OrderLine.STATUS_TO_BE_PRINTED)
        self.assertEqual(self.order.status, Order.STATUS_NEEDS_PRINTING)
        self.assertEqual(ProductNameAlias.objects.get().design, design)

    def test_create_unmatched_sku_requires_a_colour(self) -> None:
        response = self._post(
            action="create_unmatched_sku", design_name="Delulu Corrected", colour=""
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.line.refresh_from_db()
        self.assertIsNone(self.line.printed_sku_id)

    def test_repairing_an_already_fixed_row_reports_a_stale_page(self) -> None:
        sku = PrintedSKU.objects.create(
            design=Design.objects.create(name="Delulu Corrected"), colour="Black", size="M"
        )
        self._post(action="link_unmatched", printed_sku_id=str(sku.id))

        response = self._post(action="link_unmatched", printed_sku_id=str(sku.id))

        self.assertEqual(response.status_code, 404)
        self.assertIn("reload the page", response.json()["detail"])