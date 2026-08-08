from django.test import SimpleTestCase

from core.services.shopify import _extract_variant_and_size


class ShopifyVariantParsingTests(SimpleTestCase):
    def test_bare_supported_variant_is_treated_as_size(self) -> None:
        variant, size = _extract_variant_and_size("XXL", None)

        self.assertIsNone(variant)
        self.assertEqual(size, "XXL")