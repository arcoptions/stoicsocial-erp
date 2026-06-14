from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import BankTransaction, Expense, Invoice
from core.services.finance import InvoiceService


def _normalize_entity(value: object) -> str:
    """Normalize entity labels from the audit workbook to ERP naming."""
    cleaned = str(value or "").strip()
    if cleaned.lower() == "bold and italic":
        return "Bold & Italic"
    return cleaned


def _to_paise(value: object) -> int:
    """Convert numeric spreadsheet values to paise."""
    if pd.isna(value) or value == "":
        return 0
    return int(round(float(value) * 100))


class Command(BaseCommand):
    help = "Seed finance sample data from the real audit workbook and create representative invoices."

    def add_arguments(self, parser) -> None:
        """Register command arguments."""
        parser.add_argument(
            "--audit-file",
            default=r"C:\Users\abhiramnarla\Downloads\Stoic_Social_Master_Audit_Master.xlsx",
            help="Path to the audit workbook.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete previously seeded finance sample data before importing.",
        )

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Import transactions and seed representative finance records."""
        audit_path = Path(options["audit_file"])
        if not audit_path.exists():
            raise CommandError(f"Audit workbook not found: {audit_path}")

        if options["reset"]:
            self._reset_seeded_data()

        dataframe = self._load_audit_sheet(audit_path)
        created_transactions = self._seed_bank_transactions(dataframe)
        created_expenses = self._seed_expenses(dataframe)
        created_invoices = self._seed_invoices(dataframe)

        self.stdout.write(self.style.SUCCESS("Finance sample data seeded successfully."))
        self.stdout.write(f"- Bank transactions created: {created_transactions}")
        self.stdout.write(f"- Expenses created: {created_expenses}")
        self.stdout.write(f"- Invoices created: {created_invoices}")

    def _reset_seeded_data(self) -> None:
        """Remove previously seeded finance data from prior runs."""
        Invoice.objects.filter(invoice_number__startswith="SAMPLE-FIN-").delete()
        Expense.objects.filter(description__startswith="[FINANCE SAMPLE]").delete()

    def _load_audit_sheet(self, audit_path: Path) -> pd.DataFrame:
        """Load the primary audit sheet and drop obvious summary rows."""
        dataframe = pd.read_excel(audit_path, sheet_name="Master Sheet")
        dataframe = dataframe.rename(
            columns={
                "Cheque No/Reference No": "reference_no",
                "Transaction Date": "transaction_date",
                "Description": "description",
                "Withdrawals": "withdrawals",
                "Deposits": "deposits",
                "Running Balance": "running_balance",
                "Entity": "entity",
                "Remarks": "remarks",
                "Person": "person",
                "Additonal Remarks": "additional_remarks",
            }
        )
        dataframe = dataframe[dataframe["description"].notna()].copy()
        dataframe = dataframe[~dataframe["description"].astype(str).str.contains("Row Labels", case=False, na=False)]
        dataframe = dataframe[~dataframe["description"].astype(str).str.contains("Sum of", case=False, na=False)]
        return dataframe

    def _seed_bank_transactions(self, dataframe: pd.DataFrame) -> int:
        """Create bank transaction records from the audit workbook."""
        created_count = 0
        for _, row in dataframe.iterrows():
            transaction_date = pd.to_datetime(row.get("transaction_date"), errors="coerce")
            description = str(row.get("description", "")).strip()
            if pd.isna(transaction_date) or not description:
                continue

            _, created = BankTransaction.objects.update_or_create(
                transaction_date=transaction_date.date(),
                description=description,
                reference_no=str(row.get("reference_no", "")).strip(),
                defaults={
                    "withdrawals": _to_paise(row.get("withdrawals")),
                    "deposits": _to_paise(row.get("deposits")),
                    "cheque_no": "",
                    "entity": _normalize_entity(row.get("entity")),
                    "person": str(row.get("person", "")).strip(),
                    "remarks": str(row.get("remarks", "")).strip(),
                    "match_confidence": "manual_matched",
                    "running_balance": _to_paise(row.get("running_balance")) or None,
                },
            )
            if created:
                created_count += 1
        return created_count

    def _seed_expenses(self, dataframe: pd.DataFrame) -> int:
        """Create pending sample expenses derived from real withdrawal rows."""
        candidate_rows = dataframe[
            (dataframe["withdrawals"].fillna(0) > 0)
            & dataframe["remarks"].notna()
        ].head(12)

        created_count = 0
        for _, row in candidate_rows.iterrows():
            transaction_date = pd.to_datetime(row.get("transaction_date"), errors="coerce")
            if pd.isna(transaction_date):
                continue

            description = f"[FINANCE SAMPLE] {str(row.get('remarks', '')).strip() or 'Imported audit expense'}"
            expense, created = Expense.objects.get_or_create(
                expense_date=transaction_date.date(),
                paid_by=str(row.get("person", "") or "Finance Team").strip() or "Finance Team",
                entity=_normalize_entity(row.get("entity")) or "Bold & Italic",
                amount=_to_paise(row.get("withdrawals")),
                description=description,
                defaults={
                    "person": str(row.get("person", "")).strip(),
                    "remarks": str(row.get("additional_remarks", "")).strip(),
                    "status": Expense.Status.PENDING,
                },
            )
            if created:
                created_count += 1
            else:
                expense.person = expense.person or str(row.get("person", "")).strip()
                expense.remarks = expense.remarks or str(row.get("additional_remarks", "")).strip()
                expense.save(update_fields=["person", "remarks"])
        return created_count

    def _seed_invoices(self, dataframe: pd.DataFrame) -> int:
        """Create a few representative invoices from real client payment rows."""
        deposit_rows = dataframe[
            (dataframe["deposits"].fillna(0) > 0)
            & dataframe["person"].notna()
        ].copy()
        deposit_rows = deposit_rows[deposit_rows["person"].astype(str).str.strip() != ""]
        deposit_rows = deposit_rows.head(5)

        created_count = 0
        for index, row in enumerate(deposit_rows.itertuples(index=False), start=1):
            transaction_date = pd.to_datetime(getattr(row, "transaction_date", None), errors="coerce")
            if pd.isna(transaction_date):
                continue

            invoice_number = f"SAMPLE-FIN-{index:03d}"
            if Invoice.objects.filter(invoice_number=invoice_number).exists():
                continue

            deposit_paise = _to_paise(getattr(row, "deposits", 0))
            taxable_amount = int(round(deposit_paise / 1.18)) if deposit_paise else 0
            if taxable_amount <= 0:
                continue

            InvoiceService.create_invoice(
                invoice_type=Invoice.InvoiceType.TAX_INVOICE,
                invoice_number=invoice_number,
                invoice_date=transaction_date.date(),
                order_date=transaction_date.date(),
                client_name=str(getattr(row, "person", "Client")).strip(),
                client_address="Imported from audit workbook sample data",
                client_gstin="",
                place_of_supply=Invoice.PlaceOfSupply.TELANGANA,
                line_items=[
                    {
                        "description": str(getattr(row, "remarks", "Consulting Services") or "Consulting Services"),
                        "hsn_sac": "9983",
                        "quantity": 1,
                        "rate": taxable_amount,
                    }
                ],
                discount_amount=0,
                deductions_amount=0,
            )
            created_count += 1
        return created_count