from __future__ import annotations

from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import BaseCommand, call_command

from core.models import BankTransaction, Expense, Invoice, Order, OrderLine, PrintJob


class Command(BaseCommand):
    help = "Seed frozen test data for end-to-end verification across inventory, sales, and finance."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--skip-finance",
            action="store_true",
            help="Skip finance seeding command.",
        )
        parser.add_argument(
            "--grant-roles",
            action="store_true",
            help="Grant Inventory Manager, Sales Manager, and Finance Manager roles to the first user.",
        )

    def handle(self, *args, **options) -> None:
        self.stdout.write(self.style.NOTICE("Starting frozen test data seed..."))

        self._seed_inventory_and_orders()
        call_command("seed_qa_scenarios")

        if not options["skip_finance"]:
            self._seed_finance()

        if options["grant_roles"]:
            self._grant_roles_to_first_user()

        self._print_summary()
        self.stdout.write(self.style.SUCCESS("Frozen seed completed."))

    def _seed_inventory_and_orders(self) -> None:
        call_command("seed_from_excel")

    def _seed_finance(self) -> None:
        call_command("seed_finance_sample_data", reset=True)

    def _grant_roles_to_first_user(self) -> None:
        user_model = get_user_model()
        user = user_model.objects.order_by("id").first()
        if user is None:
            self.stdout.write(self.style.WARNING("No user found. Skipping role grants."))
            return

        for role_name in ["Inventory Manager", "Sales Manager", "Finance Manager"]:
            role, _ = Group.objects.get_or_create(name=role_name)
            user.groups.add(role)

        self.stdout.write(self.style.SUCCESS(f"Granted default roles to user: {user.username}"))

    def _print_summary(self) -> None:
        mismatch_count = Order.objects.filter(
            status=Order.Status.NEEDS_PRINTING,
            shopify_fulfillment_status__iexact="fulfilled",
        ).count()

        self.stdout.write("Data summary:")
        self.stdout.write(f"- Orders: {Order.objects.count()}")
        self.stdout.write(f"- Order lines: {OrderLine.objects.count()}")
        self.stdout.write(f"- Print jobs: {PrintJob.objects.count()}")
        self.stdout.write(f"- Expenses: {Expense.objects.count()}")
        self.stdout.write(f"- Invoices: {Invoice.objects.count()}")
        self.stdout.write(f"- Bank transactions: {BankTransaction.objects.count()}")
        self.stdout.write(f"- Fulfillment/status mismatch (should be 0): {mismatch_count}")
