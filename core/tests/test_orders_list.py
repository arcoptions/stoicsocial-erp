from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Design, Order, PrintedSKU, WebhookEvent
from core.services.shopify import ingest_order
from core.views.orders import ORDERS_PER_PAGE


class OrderListTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_superuser(
            username="orders-admin", password="test-password"
        )
        self.client.force_login(self.user)
        self.url = reverse("order-list")

    def _ingest(self, order_id: str, *, created_at: str, line_items: list[dict]) -> Order:
        return ingest_order(
            {"id": order_id, "name": f"#{order_id}", "created_at": created_at, "line_items": line_items},
            apply_inventory_side_effects=False,
        )

    def test_item_summary_merges_lines_by_product_and_size(self) -> None:
        design = Design.objects.create(name="Summary Product")
        PrintedSKU.objects.create(design=design, colour="Black", size="M")
        self._ingest(
            "summary-order-1",
            created_at="2026-08-17T09:30:00Z",
            line_items=[
                {"id": "s-1", "title": "Summary Product", "variant_title": "M", "quantity": 1},
                {"id": "s-2", "title": "Summary Product", "variant_title": "M", "quantity": 2},
                {"id": "s-3", "title": "Summary Product", "variant_title": "L", "quantity": 1},
            ],
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        order = response.context["orders"][0]
        self.assertEqual(
            [(item["size"], item["quantity"]) for item in order.item_summary],
            [("M", 3), ("L", 1)],
        )
        self.assertContains(response, "Summary Product")

    def test_unmatched_lines_are_flagged_in_the_summary(self) -> None:
        self._ingest(
            "summary-order-2",
            created_at="2026-08-17T09:30:00Z",
            line_items=[{"id": "s-4", "title": "Nobody Knows This", "variant_title": "M", "quantity": 1}],
        )

        response = self.client.get(self.url)

        order = response.context["orders"][0]
        self.assertTrue(order.item_summary[0]["unmatched"])
        self.assertEqual(order.unmatched_count, 1)

    def test_orders_are_sorted_by_the_real_shopify_date(self) -> None:
        # Ingested newest-first, so an import-time sort would return the reverse of what we expect.
        self._ingest("date-order-newer", created_at="2026-08-18T09:00:00Z", line_items=[])
        self._ingest("date-order-older", created_at="2026-08-10T09:00:00Z", line_items=[])

        response = self.client.get(self.url)

        self.assertEqual(
            [order.shopify_order_id for order in response.context["orders"]],
            ["date-order-newer", "date-order-older"],
        )

    def test_date_filter_uses_the_shopify_date_not_the_import_date(self) -> None:
        self._ingest("date-order-in", created_at="2026-08-12T09:00:00Z", line_items=[])
        self._ingest("date-order-out", created_at="2026-08-01T09:00:00Z", line_items=[])

        response = self.client.get(self.url, {"date_from": "2026-08-10"})

        self.assertEqual(
            [order.shopify_order_id for order in response.context["orders"]], ["date-order-in"]
        )

    def test_list_paginates(self) -> None:
        for index in range(ORDERS_PER_PAGE + 5):
            Order.objects.create(shopify_order_id=f"page-order-{index:03d}")

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": "2"})

        self.assertEqual(first.context["paginator"].count, ORDERS_PER_PAGE + 5)
        self.assertEqual(len(first.context["orders"]), ORDERS_PER_PAGE)
        self.assertEqual(len(second.context["orders"]), 5)
        self.assertEqual(second.context["page_obj"].number, 2)

    def test_pagination_links_preserve_the_active_filters(self) -> None:
        response = self.client.get(self.url, {"status": Order.STATUS_NEW, "page": "1"})

        self.assertIn("status=new", response.context["querystring"])
        self.assertNotIn("page=", response.context["querystring"])

    def test_sync_health_flags_a_silent_webhook_outage(self) -> None:
        event = WebhookEvent.objects.create(topic="orders/create", idempotency_key="stale-1")
        # created_at is auto_now_add, so age it with an UPDATE rather than a save().
        WebhookEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=3))

        response = self.client.get(self.url)

        health = response.context["sync_health"]
        self.assertTrue(health["is_stale"])
        self.assertFalse(health["never_received"])
        self.assertGreaterEqual(health["stale_hours"], 71)
        self.assertContains(response, "sync-banner stale")
        self.assertContains(response, "No Shopify webhook in the last 24 hours")

    def test_sync_health_flags_a_store_that_never_delivered(self) -> None:
        response = self.client.get(self.url)

        health = response.context["sync_health"]
        self.assertTrue(health["never_received"])
        self.assertIsNone(health["last_event_at"])

    def test_sync_health_is_quiet_when_webhooks_are_arriving(self) -> None:
        WebhookEvent.objects.create(topic="orders/create", idempotency_key="fresh-1")

        response = self.client.get(self.url)

        health = response.context["sync_health"]
        self.assertFalse(health["is_stale"])
        self.assertEqual(health["events_24h"], 1)
        self.assertNotContains(response, "sync-banner stale")
