from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.management.commands.seed_from_excel import _normalize_imported_statuses
from core.models import Design, Expense, Order, OrderLine, PrintedSKU
from core.views.orders import _build_dashboard_stats


class FrozenRequirementsE2ETestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.inventory_group, _ = Group.objects.get_or_create(name="Inventory Manager")
        cls.sales_group, _ = Group.objects.get_or_create(name="Sales Manager")
        cls.finance_group, _ = Group.objects.get_or_create(name="Finance Manager")

        cls.inventory_user = User.objects.create_user(username="inventory", password="testpass")
        cls.inventory_user.groups.add(cls.inventory_group)

        cls.sales_user = User.objects.create_user(username="sales", password="testpass")
        cls.sales_user.groups.add(cls.sales_group)

        cls.finance_user = User.objects.create_user(username="finance", password="testpass")
        cls.finance_user.groups.add(cls.finance_group)

        design = Design.objects.create(name="Test Tee", product_type="Tshirt", sub_category="Regular")
        cls.printed_sku = PrintedSKU.objects.create(
            design=design,
            variant="BASE",
            colour="Black",
            size="M",
            on_hand=10,
            reserved=0,
            buffer_min=1,
            buffer_target=2,
            buffer_max=3,
        )

    def test_status_normalization_respects_fulfillment_and_delivery(self) -> None:
        order_status, line_status = _normalize_imported_statuses(
            "to be printed", "fulfilled", "delivered"
        )
        self.assertEqual(order_status, Order.Status.SHIPPED)
        self.assertEqual(line_status, OrderLine.Status.SHIPPED)

    def test_expense_settle_requires_bank_reference(self) -> None:
        expense = Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Tester",
            entity="Bold & Italic",
            person="Vendor",
            amount=50000,
            description="Need settlement",
            status=Expense.Status.PENDING,
        )

        client = Client()
        self.assertTrue(client.login(username="finance", password="testpass"))
        response = client.post(reverse("expense-settle", args=[expense.id]), {"bank_reference": ""})

        self.assertEqual(response.status_code, 302)
        expense.refresh_from_db()
        self.assertEqual(expense.status, Expense.Status.PENDING)
        self.assertEqual(expense.bank_reference, "")

    def test_bulk_settle_uses_same_bank_reference(self) -> None:
        expense_1 = Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Tester",
            entity="Bold & Italic",
            person="Vendor A",
            amount=11000,
            description="Bulk settle A",
            status=Expense.Status.PENDING,
        )
        expense_2 = Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Tester",
            entity="Bold & Italic",
            person="Vendor B",
            amount=22000,
            description="Bulk settle B",
            status=Expense.Status.PENDING,
        )

        client = Client()
        self.assertTrue(client.login(username="finance", password="testpass"))
        response = client.post(
            reverse("expense-bulk-settle"),
            {
                "expense_ids": f"{expense_1.id},{expense_2.id}",
                "bank_reference": "BULK-REF-001",
            },
        )

        self.assertEqual(response.status_code, 302)
        expense_1.refresh_from_db()
        expense_2.refresh_from_db()
        self.assertEqual(expense_1.status, Expense.Status.SETTLED)
        self.assertEqual(expense_2.status, Expense.Status.SETTLED)
        self.assertEqual(expense_1.bank_reference, "BULK-REF-001")
        self.assertEqual(expense_2.bank_reference, "BULK-REF-001")

    def test_filtered_unsettled_total_updates_with_filters(self) -> None:
        Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Alice",
            entity="Bold & Italic",
            person="Vendor",
            amount=10000,
            description="Pending 1",
            status=Expense.Status.PENDING,
        )
        Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Bob",
            entity="Bold & Italic",
            person="Vendor",
            amount=30000,
            description="Pending 2",
            status=Expense.Status.PENDING,
        )
        Expense.objects.create(
            expense_date=timezone.localdate(),
            paid_by="Alice",
            entity="Bold & Italic",
            person="Vendor",
            amount=90000,
            description="Settled",
            status=Expense.Status.SETTLED,
        )

        client = Client()
        self.assertTrue(client.login(username="finance", password="testpass"))
        response = client.get(reverse("expense-list"), {"paid_by": "Alice"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_unsettled_rupees"], 100.0)

    def test_sales_dashboard_core_metrics(self) -> None:
        now = timezone.now()

        order_1 = Order.objects.create(
            shopify_order_id="s-001",
            order_no="S-001",
            customer_name="Alice",
            email="alice@example.com",
            status=Order.Status.SHIPPED,
            shopify_fulfillment_status="fulfilled",
            raw_payload={"total_price": "1000.00"},
        )
        order_2 = Order.objects.create(
            shopify_order_id="s-002",
            order_no="S-002",
            customer_name="Alice",
            email="alice@example.com",
            status=Order.Status.CANCELLED,
            shopify_fulfillment_status="unfulfilled",
            tags=["return"],
            raw_payload={"total_price": "500.00", "cancel_reason": "customer_return"},
        )
        order_3 = Order.objects.create(
            shopify_order_id="s-003",
            order_no="S-003",
            customer_name="Bob",
            email="bob@example.com",
            status=Order.Status.READY_TO_SHIP,
            shopify_fulfillment_status="partial",
            raw_payload={},
        )

        Order.objects.filter(id=order_1.id).update(created_at=now - timedelta(days=1))
        Order.objects.filter(id=order_2.id).update(created_at=now - timedelta(days=2))
        Order.objects.filter(id=order_3.id).update(created_at=now)

        OrderLine.objects.create(
            order=order_1,
            shopify_line_id="sl-1",
            product_name="Test Tee",
            variant="BASE",
            size="M",
            quantity=2,
            printed_sku=self.printed_sku,
            status=OrderLine.Status.SHIPPED,
        )
        OrderLine.objects.create(
            order=order_2,
            shopify_line_id="sl-2",
            product_name="Test Tee",
            variant="BASE",
            size="M",
            quantity=1,
            printed_sku=self.printed_sku,
            status=OrderLine.Status.CANCELLED,
        )
        OrderLine.objects.create(
            order=order_3,
            shopify_line_id="sl-3",
            product_name="Test Tee",
            variant="BASE",
            size="M",
            quantity=3,
            printed_sku=self.printed_sku,
            status=OrderLine.Status.READY_SHIP,
        )

        client = Client()
        self.assertTrue(client.login(username="sales", password="testpass"))
        response = client.get(reverse("sales-dashboard"), {"period": "all"})

        self.assertEqual(response.status_code, 200)
        insights = response.context["insights"]
        self.assertEqual(insights["total_orders"], 3)
        self.assertEqual(insights["unique_customers"], 2)
        self.assertEqual(insights["recurring_customers"], 1)
        self.assertEqual(insights["return_exchange_orders"], 1)
        self.assertEqual(insights["revenue_coverage_count"], 2)

    def test_inventory_dashboard_counts_stale_and_urgent(self) -> None:
        old_order = Order.objects.create(
            shopify_order_id="i-001",
            order_no="I-001",
            customer_name="Ops",
            status=Order.Status.NEEDS_PRINTING,
        )
        urgent_order = Order.objects.create(
            shopify_order_id="i-002",
            order_no="I-002",
            customer_name="Ops",
            status=Order.Status.IN_PRINTING,
        )
        shipped_order = Order.objects.create(
            shopify_order_id="i-003",
            order_no="I-003",
            customer_name="Ops",
            status=Order.Status.SHIPPED,
        )

        now = timezone.now()
        Order.objects.filter(id=old_order.id).update(created_at=now - timedelta(days=4))
        Order.objects.filter(id=urgent_order.id).update(created_at=now - timedelta(days=8))
        Order.objects.filter(id=shipped_order.id).update(created_at=now - timedelta(days=10))

        stats = _build_dashboard_stats()
        self.assertGreaterEqual(stats["stale"], 2)
        self.assertGreaterEqual(stats["urgent"], 1)
