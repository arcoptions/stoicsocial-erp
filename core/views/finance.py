"""Django views for financial management.

Provides:
- Expense tracking and settlement
- Bank statement reconciliation
- Invoice management
- Financial dashboard
"""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.security import finance_access_required
from core.models import (
    Expense,
    BankTransaction,
    Invoice,
)


EMPLOYEES = ["Abhiram", "Bubby", "STC", "Tarun", "Vicky"]
FINANCE_ENTITIES = ["Bold & Italic", "Socialight"]


def _parse_money_to_paise(raw_value: str) -> int:
    """Convert a rupee amount string into paise."""
    if raw_value in {None, ""}:
        return 0

    normalized = str(raw_value).replace(",", "").strip()
    try:
        return int((Decimal(normalized) * 100).quantize(Decimal("1")))
    except InvalidOperation as exc:
        raise ValueError("Enter a valid money amount.") from exc


def _paise_to_rupees(value: int | None) -> float:
    """Convert paise to rupees for display."""
    return (value or 0) / 100


def _prepare_expense_display(expenses: list[Expense] | Any) -> list[Expense]:
    """Attach display-friendly rupee values to expense objects."""
    prepared = list(expenses)
    for expense in prepared:
        expense.amount_rupees = _paise_to_rupees(expense.amount)
    return prepared


def _prepare_invoice_display(invoices: list[Invoice] | Any) -> list[Invoice]:
    """Attach display-friendly rupee values to invoice objects."""
    prepared = list(invoices)
    for invoice in prepared:
        invoice.grand_total_rupees = _paise_to_rupees(invoice.grand_total_amount)
        invoice.subtotal_rupees = _paise_to_rupees(invoice.subtotal_amount)
        invoice.discount_rupees = _paise_to_rupees(invoice.discount_amount)
        invoice.deductions_rupees = _paise_to_rupees(invoice.deductions_amount)
        invoice.net_taxable_rupees = _paise_to_rupees(invoice.net_taxable_amount)
        invoice.tax_rupees = _paise_to_rupees(invoice.tax_amount)
    return prepared


def _build_reconciliation_rows(matched_df: Any) -> list[dict[str, Any]]:
    """Normalize matched dataframe rows into session-safe dictionaries."""
    rows: list[dict[str, Any]] = []
    for index, row in matched_df.iterrows():
        withdrawals = int(row.get("withdrawals") or 0)
        deposits = int(row.get("deposits") or 0)
        amount = deposits or withdrawals
        transaction_date = row.get("transaction_date")

        if hasattr(transaction_date, "isoformat"):
            transaction_date_value = transaction_date.isoformat()
        else:
            transaction_date_value = str(transaction_date)

        rows.append(
            {
                "id": str(index),
                "transaction_date": transaction_date_value,
                "date": transaction_date_value,
                "description": str(row.get("description", "")).strip(),
                "withdrawals": withdrawals,
                "deposits": deposits,
                "amount": f"{_paise_to_rupees(amount):.2f}",
                "cheque_no": str(row.get("cheque_no", "")).strip(),
                "reference_no": str(row.get("reference_no", "")).strip(),
                "entity": str(row.get("entity", "")).strip(),
                "person": str(row.get("person", "")).strip(),
                "remarks": str(row.get("remarks", "")).strip(),
                "match_confidence": str(row.get("match_confidence", "needs_review")),
                "running_balance": int(row.get("running_balance") or 0),
            }
        )
    return rows


@login_required
@finance_access_required
def finance_dashboard(request):
    """Financial dashboard with analytics."""
    period = request.GET.get("period", "all")
    entity_view = request.GET.get("entity_view", "all")

    expenses_qs = Expense.objects.all()
    transactions_qs = BankTransaction.objects.all()

    if entity_view != "all":
        expenses_qs = expenses_qs.filter(entity=entity_view)
        transactions_qs = transactions_qs.filter(entity=entity_view)

    total_revenue = transactions_qs.aggregate(Sum("deposits"))["deposits__sum"] or 0
    total_expenses = transactions_qs.aggregate(Sum("withdrawals"))["withdrawals__sum"] or 0
    net_flow = total_revenue - total_expenses

    last_txn = transactions_qs.order_by("-transaction_date").first()
    closing_balance = last_txn.running_balance if last_txn else 0

    pending_expenses = expenses_qs.filter(status=Expense.Status.PENDING).count()
    settled_expenses = expenses_qs.filter(status=Expense.Status.SETTLED).count()
    rejected_expenses = expenses_qs.filter(status=Expense.Status.REJECTED).count()

    context = {
        "total_revenue": _paise_to_rupees(total_revenue),
        "total_expenses": _paise_to_rupees(total_expenses),
        "net_flow": _paise_to_rupees(net_flow),
        "closing_balance": _paise_to_rupees(closing_balance),
        "pending_expenses": pending_expenses,
        "settled_expenses": settled_expenses,
        "rejected_expenses": rejected_expenses,
        "period": period,
        "entity_view": entity_view,
        "entities": Expense.objects.values_list("entity", flat=True).distinct(),
    }
    return render(request, "core/finance/dashboard.html", context)


@login_required
@finance_access_required
def expense_list(request):
    """List expenses with filtering."""
    status_filter = request.GET.get("status", "")
    paid_by_filter = request.GET.get("paid_by", "")
    entity_filter = request.GET.get("entity", "")

    expenses = Expense.objects.all()

    if status_filter:
        expenses = expenses.filter(status=status_filter)
    if paid_by_filter:
        expenses = expenses.filter(paid_by=paid_by_filter)
    if entity_filter:
        expenses = expenses.filter(entity=entity_filter)

    total_unsettled_paise = (
        expenses.filter(status=Expense.Status.PENDING).aggregate(total=Sum("amount"))["total"] or 0
    )

    context = {
        "expenses": _prepare_expense_display(expenses),
        "status_filter": status_filter,
        "paid_by_filter": paid_by_filter,
        "entity_filter": entity_filter,
        "total_unsettled_rupees": _paise_to_rupees(total_unsettled_paise),
        "paid_by_options": Expense.objects.values_list("paid_by", flat=True).distinct(),
        "entities": Expense.objects.values_list("entity", flat=True).distinct(),
        "statuses": Expense.Status.choices,
    }
    return render(request, "core/finance/expense_list.html", context)


@login_required
@finance_access_required
@require_http_methods(["GET", "POST"])
def expense_create(request):
    """Create a new expense."""
    form_data = {
        "expense_date": request.POST.get("expense_date", ""),
        "paid_by": request.POST.get("paid_by", ""),
        "entity": request.POST.get("entity", ""),
        "person": request.POST.get("person", ""),
        "amount": request.POST.get("amount", ""),
        "description": request.POST.get("description", ""),
        "remarks": request.POST.get("remarks", ""),
    }
    errors: list[str] = []

    if request.method == "POST":
        from core.services.finance import ExpenseService

        required_fields = {
            "Expense date": form_data["expense_date"],
            "Employee": form_data["paid_by"],
            "Entity": form_data["entity"],
            "Amount": form_data["amount"],
            "Person/Client": form_data["person"],
        }
        for label, value in required_fields.items():
            if not str(value).strip():
                errors.append(f"{label} is required.")

        if not errors:
            try:
                expense = ExpenseService.create_expense(
                    expense_date=form_data["expense_date"],
                    paid_by=form_data["paid_by"],
                    entity=form_data["entity"],
                    amount=_parse_money_to_paise(form_data["amount"]),
                    description=form_data["description"],
                    person=form_data["person"],
                    remarks=form_data["remarks"],
                )
                messages.success(request, f"Expense {expense.id} created successfully.")
                return redirect("expense-list")
            except ValueError as exc:
                errors.append(str(exc))

    context = {
        "employees": EMPLOYEES,
        "entities": FINANCE_ENTITIES,
        "errors": errors,
        "form_data": form_data,
    }
    return render(request, "core/finance/expense_form.html", context)


@login_required
@finance_access_required
def expense_detail(request, expense_id: str):
    """View expense details."""
    expense = get_object_or_404(Expense, id=expense_id)
    expense.amount_rupees = _paise_to_rupees(expense.amount)
    
    context = {
        "expense": expense,
    }
    return render(request, "core/finance/expense_detail.html", context)


@login_required
@finance_access_required
@require_http_methods(["POST"])
def expense_settle(request, expense_id: str):
    """Mark expense as settled with bank reference."""
    from django.db import transaction as db_transaction
    
    expense = get_object_or_404(Expense, id=expense_id)
    
    if expense.status != Expense.Status.PENDING:
        messages.error(request, f"Only pending expenses can be settled. This expense is {expense.get_status_display()}.")
        return redirect("expense-detail", expense_id=expense_id)
    
    bank_reference = request.POST.get("bank_reference", "").strip()
    if not bank_reference:
        messages.error(request, "Bank transaction reference is required to settle an expense.")
        return redirect("expense-detail", expense_id=expense_id)
    
    try:
        with db_transaction.atomic():
            expense.status = Expense.Status.SETTLED
            expense.bank_reference = bank_reference
            expense.save()
        
        messages.success(request, f"Expense {expense.id} marked as settled with bank reference {bank_reference}.")
    except Exception as exc:
        messages.error(request, f"Could not settle expense: {exc}")
    
    return redirect("expense-list")


@login_required
@finance_access_required
@require_http_methods(["POST"])
def expense_bulk_settle(request):
    """Bulk settle multiple expenses with bank reference."""
    from django.db import transaction as db_transaction
    
    expense_ids = request.POST.get("expense_ids", "").split(",")
    bank_reference = request.POST.get("bank_reference", "").strip()
    
    if not bank_reference:
        messages.error(request, "Bank transaction reference is required to settle expenses.")
        return redirect("expense-list")
    
    if not expense_ids or expense_ids == [""]:
        messages.error(request, "No expenses selected.")
        return redirect("expense-list")
    
    settled_count = 0
    failed_count = 0
    
    try:
        with db_transaction.atomic():
            for expense_id in expense_ids:
                try:
                    expense = Expense.objects.get(id=expense_id)
                    if expense.status == Expense.Status.PENDING:
                        expense.status = Expense.Status.SETTLED
                        expense.bank_reference = bank_reference
                        expense.save()
                        settled_count += 1
                    else:
                        failed_count += 1
                except Expense.DoesNotExist:
                    failed_count += 1
    except Exception as exc:
        messages.error(request, f"Could not settle expenses: {exc}")
        return redirect("expense-list")
    
    if settled_count > 0:
        messages.success(request, f"Successfully settled {settled_count} expense{'s' if settled_count > 1 else ''} with bank reference {bank_reference}.")
    if failed_count > 0:
        messages.warning(request, f"{failed_count} expense{'s' if failed_count > 1 else ''} could not be settled.")
    
    return redirect("expense-list")


@login_required
@finance_access_required
def reconciliation_view(request):
    """Bank reconciliation interface."""
    matched_rows = request.session.get("bank_statement_data", [])

    if request.method == "POST":
        if request.POST.get("save_matches") == "true":
            created_count = 0
            for row in matched_rows:
                _, created = BankTransaction.objects.update_or_create(
                    transaction_date=row["transaction_date"],
                    description=row["description"],
                    reference_no=row["reference_no"],
                    defaults={
                        "withdrawals": row["withdrawals"],
                        "deposits": row["deposits"],
                        "cheque_no": row["cheque_no"],
                        "entity": row["entity"],
                        "person": row["person"],
                        "remarks": row["remarks"],
                        "match_confidence": row["match_confidence"],
                        "running_balance": row["running_balance"] or None,
                    },
                )
                if created:
                    created_count += 1

            request.session.pop("bank_statement_data", None)
            messages.success(request, f"Saved {created_count} bank transactions for reconciliation.")
            return redirect("reconciliation")

        from core.services.finance import BankStatementParser, SmartTransactionMatcher

        uploaded_file = request.FILES.get("bank_statement")
        if not uploaded_file:
            messages.error(request, "Select a bank statement file to upload.")
            return redirect("reconciliation")

        parser = BankStatementParser()
        try:
            file_suffix = os.path.splitext(uploaded_file.name)[1] or ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            new_transactions = parser.clean_bank_statement(tmp_path)
            os.unlink(tmp_path)

            historical_df = None
            existing = list(
                BankTransaction.objects.all().values(
                    "description", "entity", "person", "remarks"
                )
            )
            if existing:
                import pandas as pd

                historical_df = pd.DataFrame(existing)

            matcher = SmartTransactionMatcher()
            matched_df = matcher.apply_smart_matching(new_transactions, historical_df)
            matched_rows = _build_reconciliation_rows(matched_df)
            request.session["bank_statement_data"] = matched_rows

            context = {
                "matched_data": matched_rows,
                "transaction_count": len(matched_rows),
                "auto_reconciled_count": sum(
                    1 for row in matched_rows if row["match_confidence"] == "auto_reconciled"
                ),
                "needs_review_count": sum(
                    1 for row in matched_rows if row["match_confidence"] == "needs_review"
                ),
                "pending_reconciliations": BankTransaction.objects.filter(
                    match_confidence="needs_review"
                ).count(),
            }
            return render(request, "core/finance/reconciliation.html", context)
        except Exception as exc:
            messages.error(request, f"Could not parse bank statement: {exc}")
            return redirect("reconciliation")

    context = {
        "matched_data": matched_rows,
        "transaction_count": len(matched_rows),
        "auto_reconciled_count": sum(
            1 for row in matched_rows if row["match_confidence"] == "auto_reconciled"
        ),
        "needs_review_count": sum(
            1 for row in matched_rows if row["match_confidence"] == "needs_review"
        ),
        "pending_reconciliations": BankTransaction.objects.filter(
            match_confidence="needs_review"
        ).count(),
    }
    return render(request, "core/finance/reconciliation.html", context)


@login_required
@finance_access_required
def invoice_list(request):
    """List invoices."""
    invoices = Invoice.objects.all()

    invoice_type_filter = request.GET.get("invoice_type", "")
    place_of_supply_filter = request.GET.get("place_of_supply", "")

    if invoice_type_filter:
        invoices = invoices.filter(invoice_type=invoice_type_filter)
    if place_of_supply_filter:
        invoices = invoices.filter(place_of_supply=place_of_supply_filter)

    context = {
        "invoices": _prepare_invoice_display(invoices),
        "invoice_types": Invoice.InvoiceType.choices,
        "places_of_supply": Invoice.PlaceOfSupply.choices,
        "invoice_type_filter": invoice_type_filter,
        "place_of_supply_filter": place_of_supply_filter,
    }
    return render(request, "core/finance/invoice_list.html", context)


@login_required
@finance_access_required
@require_http_methods(["GET", "POST"])
def invoice_create(request):
    """Create and generate invoice."""
    form_data = {key: request.POST.get(key, "") for key in [
        "invoice_type",
        "invoice_number",
        "invoice_date",
        "order_date",
        "client_name",
        "client_address",
        "client_gstin",
        "place_of_supply",
        "discount_amount",
        "deductions_amount",
    ]}
    errors: list[str] = []

    if request.method == "POST":
        from core.services.finance import InvoiceService

        line_items_raw = request.POST.get("line_items_json")
        line_items = json.loads(line_items_raw) if line_items_raw else []

        required_fields = {
            "Invoice type": form_data["invoice_type"],
            "Invoice number": form_data["invoice_number"],
            "Invoice date": form_data["invoice_date"],
            "Order date": form_data["order_date"],
            "Client name": form_data["client_name"],
            "Client address": form_data["client_address"],
            "Place of supply": form_data["place_of_supply"],
        }
        for label, value in required_fields.items():
            if not str(value).strip():
                errors.append(f"{label} is required.")

        if not line_items:
            errors.append("Add at least one line item before creating the invoice.")

        parsed_line_items: list[dict[str, Any]] = []
        if not errors:
            try:
                for item in line_items:
                    description = str(item.get("description", "")).strip()
                    quantity = int(item.get("quantity") or 0)
                    if not description or quantity <= 0:
                        continue

                    parsed_line_items.append(
                        {
                            "description": description,
                            "hsn_sac": str(item.get("hsn_sac", "")).strip(),
                            "quantity": quantity,
                            "rate": _parse_money_to_paise(str(item.get("rate", 0))),
                        }
                    )
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))

        if not parsed_line_items and not errors:
            errors.append("Add at least one valid line item.")

        if not errors:
            try:
                invoice = InvoiceService.create_invoice(
                    invoice_type=form_data["invoice_type"],
                    invoice_number=form_data["invoice_number"],
                    invoice_date=form_data["invoice_date"],
                    order_date=form_data["order_date"],
                    client_name=form_data["client_name"],
                    client_address=form_data["client_address"],
                    client_gstin=form_data["client_gstin"],
                    place_of_supply=form_data["place_of_supply"] or "telangana",
                    line_items=parsed_line_items,
                    discount_amount=_parse_money_to_paise(form_data.get("discount_amount", "0")),
                    deductions_amount=_parse_money_to_paise(form_data.get("deductions_amount", "0")),
                )
                messages.success(request, f"Invoice {invoice.invoice_number} created successfully.")
                return redirect("invoice-detail", invoice_id=invoice.id)
            except ValueError as exc:
                errors.append(str(exc))

    context = {
        "places_of_supply": Invoice.PlaceOfSupply.choices,
        "invoice_types": Invoice.InvoiceType.choices,
        "errors": errors,
        "form_data": form_data,
    }
    return render(request, "core/finance/invoice_form.html", context)


@login_required
@finance_access_required
def invoice_detail(request, invoice_id):
    """View invoice details and generate PDF."""
    invoice = get_object_or_404(Invoice, id=invoice_id)
    line_items = list(invoice.line_items.all())
    for item in line_items:
        item.rate_rupees = _paise_to_rupees(item.rate)
        item.amount_rupees = _paise_to_rupees(item.amount)

    _prepare_invoice_display([invoice])

    context = {
        "invoice": invoice,
        "line_items": line_items,
    }
    return render(request, "core/finance/invoice_detail.html", context)
