from datetime import datetime, timezone
from importlib import import_module

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase

from core.models import Design, Order, OrderLine, PrintedSKU, ProductNameAlias
from core.services.shopify import (
    _extract_variant_and_size,
    _resolve_printed_sku,
    ingest_order,
    relink_order_line,
    remember_product_name_alias,
)


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


class ShopifyOrderIngestionTests(TestCase):
    def test_backfill_marks_cancelled_order_and_lines_cancelled(self) -> None:
        order = ingest_order(
            {
                "id": "cancelled-order-1",
                "name": "#1001",
                "cancelled_at": "2026-08-16T12:00:00Z",
                "line_items": [
                    {
                        "id": "cancelled-line-1",
                        "title": "Cancelled Product",
                        "variant_title": "M",
                        "quantity": 1,
                    }
                ],
            },
            apply_inventory_side_effects=False,
        )

        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertEqual(order.lines.get().status, OrderLine.STATUS_CANCELLED)

    def test_stores_real_shopify_timestamps(self) -> None:
        order = ingest_order(
            {
                "id": "dated-order-1",
                "name": "#2001",
                "created_at": "2026-08-17T09:30:00+05:30",
                "updated_at": "2026-08-18T11:00:00+05:30",
                "cancelled_at": "2026-08-18T12:15:00+05:30",
                "line_items": [],
            },
            apply_inventory_side_effects=False,
        )

        self.assertIsNotNone(order.shopify_created_at)
        self.assertEqual(order.shopify_created_at.isoformat(), "2026-08-17T09:30:00+05:30")
        self.assertEqual(order.shopify_updated_at.isoformat(), "2026-08-18T11:00:00+05:30")
        self.assertEqual(order.cancelled_at.isoformat(), "2026-08-18T12:15:00+05:30")
        # placed_at is what the dashboard sorts and filters on.
        self.assertEqual(order.placed_at, order.shopify_created_at)

    def test_tolerates_missing_and_malformed_dates(self) -> None:
        order = ingest_order(
            {"id": "undated-order-1", "name": "#2002", "created_at": "not-a-date", "line_items": []},
            apply_inventory_side_effects=False,
        )

        self.assertIsNone(order.shopify_created_at)
        self.assertIsNone(order.cancelled_at)
        # Falls back to the import time so the dashboard never shows a blank date.
        self.assertEqual(order.placed_at, order.created_at)

    def test_orders_updated_upserts_instead_of_duplicating(self) -> None:
        payload = {
            "id": "updatable-order-1",
            "name": "#3001",
            "created_at": "2026-08-17T09:30:00Z",
            "line_items": [
                {"id": "line-a", "title": "Updatable Product", "variant_title": "M", "quantity": 1}
            ],
        }
        ingest_order(payload, apply_inventory_side_effects=False)

        updated_payload = dict(payload, email="buyer@example.com", updated_at="2026-08-18T10:00:00Z")
        order = ingest_order(updated_payload, apply_inventory_side_effects=False)

        self.assertEqual(Order.objects.filter(shopify_order_id="updatable-order-1").count(), 1)
        self.assertEqual(order.email, "buyer@example.com")
        self.assertEqual(order.lines.count(), 1)

    def test_partial_payload_does_not_wipe_stored_dates(self) -> None:
        ingest_order(
            {
                "id": "keep-dates-1",
                "name": "#3002",
                "created_at": "2026-08-17T09:30:00Z",
                "line_items": [],
            },
            apply_inventory_side_effects=False,
        )

        order = ingest_order(
            {"id": "keep-dates-1", "name": "#3002", "line_items": []},
            apply_inventory_side_effects=False,
        )

        self.assertIsNotNone(order.shopify_created_at)


class ShopifyDateBackfillMigrationTests(TestCase):
    """The 0008 data migration recovers real order dates for orders imported before the fields existed."""

    def _run_backfill(self) -> None:
        migration = import_module(
            "core.migrations.0008_alter_designassetfile_options_order_cancelled_at_and_more"
        )
        migration.backfill_shopify_dates(django_apps, None)

    def test_backfills_dates_from_the_stored_raw_payload(self) -> None:
        order = Order.objects.create(
            shopify_order_id="legacy-order-1",
            order_no="#9001",
            raw_payload={
                "id": "legacy-order-1",
                "created_at": "2026-08-14T18:05:00+05:30",
                "updated_at": "2026-08-15T10:00:00+05:30",
                "cancelled_at": "2026-08-15T11:30:00+05:30",
            },
        )

        self._run_backfill()

        order.refresh_from_db()
        # Compared as instants: the DB normalises everything to UTC on read.
        self.assertEqual(order.shopify_created_at, datetime(2026, 8, 14, 12, 35, tzinfo=timezone.utc))
        self.assertEqual(order.shopify_updated_at, datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc))
        self.assertEqual(order.cancelled_at, datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc))

    def test_leaves_orders_without_usable_payload_dates_alone(self) -> None:
        empty = Order.objects.create(shopify_order_id="legacy-order-2", raw_payload={})
        junk = Order.objects.create(
            shopify_order_id="legacy-order-3", raw_payload={"created_at": "yesterday"}
        )

        self._run_backfill()

        empty.refresh_from_db()
        junk.refresh_from_db()
        self.assertIsNone(empty.shopify_created_at)
        self.assertIsNone(junk.shopify_created_at)
        # placed_at still resolves, so the dashboard never renders a blank date.
        self.assertEqual(empty.placed_at, empty.created_at)

    def test_does_not_overwrite_dates_already_stored(self) -> None:
        order = ingest_order(
            {
                "id": "legacy-order-4",
                "name": "#9002",
                "created_at": "2026-08-17T09:30:00Z",
                "line_items": [],
            },
            apply_inventory_side_effects=False,
        )
        order.raw_payload = dict(order.raw_payload, created_at="2020-01-01T00:00:00Z")
        order.save(update_fields=["raw_payload"])

        self._run_backfill()

        order.refresh_from_db()
        self.assertEqual(order.shopify_created_at.year, 2026)


class ProductNameAliasTests(TestCase):
    def setUp(self) -> None:
        self.design = Design.objects.create(name="Delulu With Lots Of Kalalu")
        self.sku = PrintedSKU.objects.create(design=self.design, colour="Black", size="M")
        self.item = {
            "id": "aliased-line-1",
            "title": "Delulu with lots of kalalu!!",
            "variant_title": "L",
        }

    def test_unaliased_title_with_multiple_families_does_not_resolve(self) -> None:
        PrintedSKU.objects.create(design=Design.objects.create(name="Other"), colour="White", size="M")
        self.sku.design.name = "Completely Different Name"
        self.sku.design.save(update_fields=["name"])

        self.assertIsNone(_resolve_printed_sku(self.item))

    def test_alias_resolves_previously_unmatched_title_and_creates_size(self) -> None:
        self.sku.design.name = "Completely Different Name"
        self.sku.design.save(update_fields=["name"])
        remember_product_name_alias(
            source_name="Delulu with lots of kalalu!!",
            source_variant="",
            printed_sku=self.sku,
        )

        resolved = _resolve_printed_sku(self.item)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.design, self.design)
        self.assertEqual(resolved.colour, "Black")
        self.assertEqual(resolved.size, "L")

    def test_alias_is_stored_canonically_and_updated_in_place(self) -> None:
        remember_product_name_alias(
            source_name="Delulu with lots of kalalu!!", source_variant="", printed_sku=self.sku
        )
        remember_product_name_alias(
            source_name="delulu   with lots of kalalu", source_variant="", printed_sku=self.sku
        )

        self.assertEqual(ProductNameAlias.objects.count(), 1)
        alias = ProductNameAlias.objects.get()
        self.assertEqual(alias.canonical_name, "deluluwithlotsofkalalu")
        self.assertEqual(alias.design, self.design)


class RelinkOrderLineTests(TestCase):
    def _unmatched_order(self) -> Order:
        return ingest_order(
            {
                "id": "unmatched-order-1",
                "name": "#4001",
                "created_at": "2026-08-17T09:30:00Z",
                "line_items": [
                    {"id": "unmatched-line-1", "title": "Mystery Product", "variant_title": "M", "quantity": 2}
                ],
            },
            apply_inventory_side_effects=True,
        )

    def test_relink_reserves_stock_when_available(self) -> None:
        order = self._unmatched_order()
        line = order.lines.get()
        self.assertIsNone(line.printed_sku_id)
        sku = PrintedSKU.objects.create(
            design=Design.objects.create(name="Mystery Product"), colour="Black", size="M", on_hand=5
        )

        relink_order_line(line, sku)

        line.refresh_from_db()
        sku.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(line.printed_sku_id, sku.id)
        self.assertEqual(line.status, OrderLine.STATUS_READY_SHIP)
        self.assertEqual(sku.reserved, 2)
        self.assertEqual(order.status, Order.STATUS_READY_TO_SHIP)

    def test_relink_queues_for_printing_when_stock_is_short(self) -> None:
        order = self._unmatched_order()
        line = order.lines.get()
        sku = PrintedSKU.objects.create(
            design=Design.objects.create(name="Mystery Product"), colour="Black", size="M", on_hand=1
        )

        relink_order_line(line, sku)

        line.refresh_from_db()
        sku.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(line.status, OrderLine.STATUS_TO_BE_PRINTED)
        self.assertEqual(sku.reserved, 0)
        self.assertEqual(order.status, Order.STATUS_NEEDS_PRINTING)

    def test_relink_adopts_sku_size_when_the_line_had_none(self) -> None:
        order = ingest_order(
            {
                "id": "sizeless-order-1",
                "name": "#4002",
                "created_at": "2026-08-17T09:30:00Z",
                "line_items": [
                    {"id": "sizeless-line-1", "title": "Sizeless Product", "quantity": 1}
                ],
            },
            apply_inventory_side_effects=True,
        )
        line = order.lines.get()
        self.assertEqual(line.size, "")
        sku = PrintedSKU.objects.create(
            design=Design.objects.create(name="Sizeless Product"), colour="Black", size="XL", on_hand=3
        )

        relink_order_line(line, sku)

        line.refresh_from_db()
        self.assertEqual(line.size, "XL")
