from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.models import BlankSKU, Order, Vendor


class EmptyDomainResetTests(TestCase):
    def test_empty_reset_preserves_users_and_removes_business_data(self) -> None:
        user = get_user_model().objects.create_user(username="operator", password="test-password")
        Vendor.objects.create(name="Printer")
        BlankSKU.objects.create(fabric="180 GSM", colour="Black", size="M", on_hand=10)
        Order.objects.create(shopify_order_id="shopify-1", order_no="#1")

        call_command("reset_and_seed_domain_data", "--yes", "--empty")

        self.assertTrue(get_user_model().objects.filter(id=user.id).exists())
        self.assertFalse(Vendor.objects.exists())
        self.assertFalse(BlankSKU.objects.exists())
        self.assertFalse(Order.objects.exists())