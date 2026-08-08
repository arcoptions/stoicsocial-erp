from django.test import SimpleTestCase, TestCase

from core.models import Design, PrintedSKU
from core.services.shopify import _extract_variant_and_size, _resolve_printed_sku


class ShopifyVariantParsingTests(SimpleTestCase):
    def test_bare_supported_variant_is_treated_as_size(self) -> None:
        variant, size = _extract_variant_and_size("XXL", None)

        self.assertIsNone(variant)
        self.assertEqual(size, "XXL")


class ShopifySkuResolutionTests(TestCase):
    def test_creates_new_size_for_unambiguous_sku_family(self) -> None:
        design = Design.objects.create(name="Size Only Product")
        PrintedSKU.objects.create(design=design, colour="Black", size="M")

        resolved = _resolve_printed_sku(
            {"id": "line-1", "title": "Size Only Product", "variant_title": "XXL"}
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.design, design)
        self.assertEqual(resolved.colour, "Black")
        self.assertEqual(resolved.size, "XXL")
        self.assertEqual(resolved.on_hand, 0)

    def test_does_not_guess_when_product_has_multiple_colour_families(self) -> None:
        design = Design.objects.create(name="Multi Colour Product")
        PrintedSKU.objects.create(design=design, colour="Black", size="M")
        PrintedSKU.objects.create(design=design, colour="White", size="M")

        resolved = _resolve_printed_sku(
            {"id": "line-2", "title": "Multi Colour Product", "variant_title": "XXL"}
        )

        self.assertIsNone(resolved)
        self.assertEqual(PrintedSKU.objects.filter(design=design).count(), 2)

    def test_prefers_literal_title_when_designs_differ_only_by_case(self) -> None:
        expected_design = Design.objects.create(name="Case sensitive product")
        other_design = Design.objects.create(name="Case Sensitive Product")
        PrintedSKU.objects.create(design=expected_design, colour="Black", size="M")
        PrintedSKU.objects.create(design=other_design, colour="White", size="M")

        resolved = _resolve_printed_sku(
            {"id": "line-3", "title": "Case sensitive product", "variant_title": "XXL"}
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.design, expected_design)
        self.assertEqual(resolved.colour, "Black")