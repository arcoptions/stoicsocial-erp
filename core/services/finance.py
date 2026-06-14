"""Financial management services for BoldERP.

Implements:
- Bank statement parsing and cleaning
- Smart transaction matching (auto-reconciliation)
- Invoice generation with GST/IGST handling
- Expense tracking and settlement

Adapted from bold-finance Streamlit app logic.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd
from django.db import transaction

from core.models import (
    BankTransaction,
    Expense,
    Invoice,
    InvoiceLineItem,
    Reconciliation,
)

logger = logging.getLogger(__name__)


class BankStatementParser:
    """Parse and clean bank statements from CSV/Excel files."""

    # Define column mapping patterns (case-insensitive, whitespace trimmed)
    DEFAULT_COLUMN_PATTERNS = {
        "date": [r"^date$", r"^transaction\s*date$", r"^value\s*date$"],
        "description": [r"^description$", r"^narrative$", r"^detail$"],
        "withdrawals": [r"^withdrawal", r"^debit", r"^out"],
        "deposits": [r"^deposit", r"^credit", r"^in"],
        "cheque_no": [r"^cheque", r"^check"],
        "reference_no": [r"^reference", r"^ref", r"^transaction\s*ref"],
    }

    @staticmethod
    def find_header_row(df: pd.DataFrame, max_rows: int = 20) -> int:
        """Find the actual header row by looking for numeric/date patterns.
        
        Skips bank logos, disclaimers, and other junk at the top of the statement.
        """
        for idx, row in df.iterrows():
            if idx >= max_rows:
                break
            # Check if row contains expected column names
            row_str = " ".join(str(cell).lower() for cell in row if pd.notna(cell))
            if any(
                pattern in row_str
                for pattern in [
                    "date",
                    "description",
                    "debit",
                    "credit",
                    "withdrawal",
                    "deposit",
                ]
            ):
                return idx
        return 0

    @staticmethod
    def normalize_column_names(df: pd.DataFrame, patterns: dict) -> dict:
        """Map found columns to standard names."""
        found_columns = {}
        df_columns_lower = {col.lower().strip(): col for col in df.columns}

        for standard_name, regex_patterns in patterns.items():
            for col_lower, col_orig in df_columns_lower.items():
                for pattern in regex_patterns:
                    if re.search(pattern, col_lower):
                        found_columns[standard_name] = col_orig
                        break
                if standard_name in found_columns:
                    break

        return found_columns

    @staticmethod
    def clean_amount(value) -> int:
        """Convert amount string to paise (integer)."""
        if pd.isna(value) or value == "":
            return 0
        if isinstance(value, (int, float)):
            return int(value * 100)
        # Remove currency symbols, commas
        value = str(value).replace("₹", "").replace(",", "").strip()
        try:
            return int(float(value) * 100)
        except ValueError:
            return 0

    def clean_bank_statement(
        self,
        file_path: str,
        file_format: str = "auto",
    ) -> pd.DataFrame:
        """Parse and clean bank statement from CSV or Excel.
        
        Args:
            file_path: Path to uploaded file
            file_format: 'csv', 'excel', or 'auto' (detect from extension)
            
        Returns:
            Cleaned DataFrame with standardized columns
        """
        # Read file
        try:
            if file_format == "auto":
                if file_path.endswith(".csv"):
                    df = pd.read_csv(file_path, encoding="utf-8")
                else:
                    df = pd.read_excel(file_path)
            elif file_format == "csv":
                df = pd.read_csv(file_path, encoding="utf-8")
            else:
                df = pd.read_excel(file_path)
        except UnicodeDecodeError:
            # Fallback to latin-1 for CSV with encoding issues
            df = pd.read_csv(file_path, encoding="latin-1")

        # Find header row (skip junk at top)
        header_idx = self.find_header_row(df)
        if header_idx > 0:
            df = df.iloc[header_idx:].reset_index(drop=True)
            df.columns = df.iloc[0]  # Set header
            df = df.iloc[1:].reset_index(drop=True)

        # Normalize column names
        col_mapping = self.normalize_column_names(df, self.DEFAULT_COLUMN_PATTERNS)

        # Build clean dataframe
        clean_rows = []
        for _, row in df.iterrows():
            try:
                # Extract values with defaults
                txn_date = pd.to_datetime(
                    row.get(col_mapping.get("date"), ""), errors="coerce"
                )
                if pd.isna(txn_date):
                    continue  # Skip invalid date rows

                description = str(row.get(col_mapping.get("description"), "")).strip()
                withdrawals = self.clean_amount(
                    row.get(col_mapping.get("withdrawals"), 0)
                )
                deposits = self.clean_amount(row.get(col_mapping.get("deposits"), 0))
                cheque_no = str(row.get(col_mapping.get("cheque_no"), "")).strip()
                reference_no = str(row.get(col_mapping.get("reference_no"), "")).strip()

                clean_rows.append(
                    {
                        "transaction_date": txn_date.date(),
                        "description": description,
                        "withdrawals": withdrawals,
                        "deposits": deposits,
                        "cheque_no": cheque_no,
                        "reference_no": reference_no,
                        "entity": "",  # To be filled by matching
                        "person": "",  # To be filled by matching
                        "remarks": "",  # To be filled by matching
                        "match_confidence": "needs_review",
                    }
                )
            except Exception as e:
                logger.warning(f"Skipping malformed row: {e}")
                continue

        return pd.DataFrame(clean_rows)


class SmartTransactionMatcher:
    """Auto-reconcile transactions using historical data and keyword matching."""

    # Regex-based rules for entity/person/remarks mapping (from bold-finance constants.py)
    DEFAULT_MAPPING_RULES = {
        "RAZORPAY|FACEBOOK": {
            "entity": "Bold & Italic",
            "remarks": "Advertising",
        },
        "TRIPURA BIO|VUESOL": {
            "entity": "Socialight",
            "remarks": "Client Services",
        },
        "GOOGLE|YOUTUBE|AMAZON": {
            "entity": "Bold & Italic",
            "remarks": "Ad Spend",
        },
        "SHOPIFY": {
            "entity": "Bold & Italic",
            "remarks": "Platform Fees",
        },
    }

    @staticmethod
    def apply_keyword_matching(
        description: str, mapping_rules: dict
    ) -> dict:
        """Match description against regex rules."""
        description_upper = description.upper()
        for pattern_str, match_data in mapping_rules.items():
            if re.search(pattern_str, description_upper):
                return match_data.copy()
        return {}

    @staticmethod
    def apply_smart_matching(
        new_df: pd.DataFrame,
        historical_df: Optional[pd.DataFrame] = None,
        mapping_rules: dict = None,
    ) -> pd.DataFrame:
        """Auto-reconcile new transactions using historical data and keyword rules.
        
        Args:
            new_df: DataFrame of new bank transactions to match
            historical_df: Historical transactions to build match dictionary from
            mapping_rules: Keyword-based matching rules
            
        Returns:
            DataFrame with matched entity/person/remarks and confidence scores
        """
        if mapping_rules is None:
            mapping_rules = SmartTransactionMatcher.DEFAULT_MAPPING_RULES

        # Build historical match dictionary (Description -> entity/person/remarks)
        history_dict = {}
        if historical_df is not None and not historical_df.empty:
            for _, row in historical_df.iterrows():
                desc = str(row.get("description", "")).strip().upper()
                if desc and row.get("entity"):
                    history_dict[desc] = {
                        "entity": row.get("entity", ""),
                        "person": row.get("person", ""),
                        "remarks": row.get("remarks", ""),
                    }

        # Apply matching
        matched_df = new_df.copy()
        for idx, row in matched_df.iterrows():
            description = str(row.get("description", "")).strip().upper()

            # Try exact match from history first
            if description in history_dict:
                match_data = history_dict[description]
                matched_df.at[idx, "entity"] = match_data.get("entity", "")
                matched_df.at[idx, "person"] = match_data.get("person", "")
                matched_df.at[idx, "remarks"] = match_data.get("remarks", "")
                matched_df.at[idx, "match_confidence"] = "auto_reconciled"
            else:
                # Try keyword matching
                keyword_match = SmartTransactionMatcher.apply_keyword_matching(
                    description, mapping_rules
                )
                if keyword_match:
                    matched_df.at[idx, "entity"] = keyword_match.get("entity", "")
                    matched_df.at[idx, "remarks"] = keyword_match.get("remarks", "")
                    matched_df.at[idx, "match_confidence"] = "auto_reconciled"

        return matched_df


class ExpenseService:
    """Manage expense tracking and settlement."""

    @staticmethod
    @transaction.atomic
    def create_expense(
        expense_date,
        paid_by: str,
        entity: str,
        amount: int,
        description: str = "",
        person: str = "",
        remarks: str = "",
    ) -> Expense:
        """Create a new expense record."""
        expense = Expense.objects.create(
            expense_date=expense_date,
            paid_by=paid_by,
            entity=entity,
            person=person,
            amount=amount,
            description=description,
            remarks=remarks,
            status=Expense.Status.PENDING,
        )
        logger.info(f"Created expense {expense.id} for {paid_by}")
        return expense

    @staticmethod
    @transaction.atomic
    def settle_expenses(
        expense_ids: list,
        bank_reference: str,
        user=None,
    ) -> list[Reconciliation]:
        """Settle multiple expenses against a bank transaction reference."""
        reconciliations = []

        # Find bank transaction
        try:
            bank_txn = BankTransaction.objects.get(reference_no=bank_reference)
        except BankTransaction.DoesNotExist:
            raise ValueError(f"Bank transaction {bank_reference} not found")

        # Link all expenses
        expenses = Expense.objects.filter(id__in=expense_ids, status=Expense.Status.PENDING)
        for expense in expenses:
            recon = Reconciliation.objects.create(
                expense=expense,
                bank_transaction=bank_txn,
                matched_by=user,
            )
            expense.status = Expense.Status.SETTLED
            expense.bank_reference = bank_reference
            expense.save(update_fields=["status", "bank_reference"])
            reconciliations.append(recon)

        logger.info(f"Settled {len(reconciliations)} expenses")
        return reconciliations


class InvoiceService:
    """Generate and manage invoices with GST/IGST."""

    COMPANY_NAME = "Bold & Italic"
    COMPANY_LEGAL = "c/o Stoic Social LLP"
    COMPANY_ADDRESS = "Hyderabad, Telangana, India"
    COMPANY_GSTIN = "36AFEFS7497C1ZM"
    COMPANY_PAN = "AFEFS7497C"
    COMPANY_BANK = "YES BANK"
    COMPANY_ACCOUNT = "Stoic Social LLP (041363400009611)"
    COMPANY_IFSC = "YESB0000413"

    @staticmethod
    def calculate_taxes(
        net_taxable_amount: int,
        place_of_supply: str,
    ) -> tuple[int, str]:
        """Calculate GST/IGST based on place of supply.
        
        Args:
            net_taxable_amount: Amount in paise
            place_of_supply: 'telangana', 'maharashtra', 'karnataka', 'delhi', or 'others'
            
        Returns:
            (tax_amount_in_paise, tax_type)
        """
        if place_of_supply == "telangana":
            # CGST (9%) + SGST (9%) = 18%
            tax = int(net_taxable_amount * 0.18)
            return tax, "CGST 9% + SGST 9%"
        else:
            # IGST (18%)
            tax = int(net_taxable_amount * 0.18)
            return tax, "IGST 18%"

    @staticmethod
    @transaction.atomic
    def create_invoice(
        invoice_type: str,
        invoice_number: str,
        invoice_date,
        order_date,
        client_name: str,
        client_address: str,
        client_gstin: str = "",
        place_of_supply: str = "telangana",
        line_items: list = None,
        discount_amount: int = 0,
        deductions_amount: int = 0,
    ) -> Invoice:
        """Create a new invoice with line items.
        
        Args:
            invoice_type: 'tax_invoice' or 'proforma'
            invoice_number: Unique invoice number
            invoice_date: Date of invoice
            order_date: Date of order
            client_name: Client/customer name
            client_address: Client address
            client_gstin: Client GSTIN (optional)
            place_of_supply: For GST routing
            line_items: List of dicts with keys: description, hsn_sac, quantity, rate
            discount_amount: Discount in paise
            deductions_amount: Other deductions in paise
            
        Returns:
            Invoice instance with line items
        """
        if line_items is None:
            line_items = []

        # Calculate totals
        subtotal = sum(item.get("quantity", 0) * item.get("rate", 0) for item in line_items)
        net_taxable = subtotal - discount_amount - deductions_amount
        tax_amount, _ = InvoiceService.calculate_taxes(net_taxable, place_of_supply)
        grand_total = net_taxable + tax_amount

        # Create invoice
        invoice = Invoice.objects.create(
            invoice_type=invoice_type,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            order_date=order_date,
            client_name=client_name,
            client_address=client_address,
            client_gstin=client_gstin,
            place_of_supply=place_of_supply,
            discount_amount=discount_amount,
            deductions_amount=deductions_amount,
            subtotal_amount=subtotal,
            net_taxable_amount=net_taxable,
            tax_amount=tax_amount,
            grand_total_amount=grand_total,
        )

        # Create line items
        for seq, item in enumerate(line_items, start=1):
            amount = item.get("quantity", 0) * item.get("rate", 0)
            InvoiceLineItem.objects.create(
                invoice=invoice,
                sequence=seq,
                description=item.get("description", ""),
                hsn_sac=item.get("hsn_sac", ""),
                quantity=item.get("quantity", 1),
                rate=item.get("rate", 0),
                amount=amount,
            )

        logger.info(f"Created invoice {invoice_number}")
        return invoice
