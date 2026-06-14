# Financial Management Module - Implementation Guide

## Overview

The Financial Management module has been integrated into BoldERP, adapting the Streamlit-based **bold-finance** application into a Django-native architecture. This module provides:

- **Expense Tracking**: Log and track employee reimbursements
- **Bank Reconciliation**: Parse bank statements and auto-match transactions
- **Invoice Management**: Generate Tax Invoices and Proforma Invoices with GST/IGST
- **Financial Dashboard**: Real-time analytics and reporting

---

## Architecture

### Data Models (`core/models.py`)

Five new models have been added to manage financial data:

#### 1. **Expense**
Employee expense reimbursement tracker.

```python
class Expense(UUIDTimestampedModel):
    expense_date: DateField
    paid_by: CharField  # Employee name
    entity: CharField  # Organization entity (Bold & Italic, Socialight, etc.)
    person: CharField  # Primary person/client
    amount: IntegerField  # Amount in paise
    description: TextField
    remarks: TextField
    status: CharField  # pending, settled, rejected
    bank_reference: CharField  # Bank txn reference when settled
```

**Features**:
- Track expenses by employee and entity
- Link expenses to bank transactions for settlement
- Audit trail with created_at/updated_at timestamps
- Indexing on status, date, and employee for fast queries

---

#### 2. **BankTransaction**
Bank statement transaction records.

```python
class BankTransaction(UUIDTimestampedModel):
    transaction_date: DateField
    description: TextField
    withdrawals: IntegerField  # Debit amount in paise
    deposits: IntegerField     # Credit amount in paise
    cheque_no: CharField
    reference_no: CharField
    entity: CharField
    person: CharField
    remarks: TextField
    match_confidence: CharField  # auto_reconciled, needs_review, manual_matched
    running_balance: IntegerField
```

**Features**:
- Stores parsed bank statement transactions
- Confidence scoring for auto-reconciliation
- Flexible categorization via entity/person/remarks
- Running balance tracking for audit trail

---

#### 3. **Reconciliation**
Links Expense to BankTransaction (many-to-one relationship).

```python
class Reconciliation(UUIDTimestampedModel):
    expense: ForeignKey(Expense, OneToOne)
    bank_transaction: ForeignKey(BankTransaction, OneToOne)
    matched_by: ForeignKey(User)
    notes: TextField
```

**Features**:
- Tracks which user matched/settled the expense
- Audit trail for compliance
- Notes field for match context

---

#### 4. **Invoice**
Invoice/Proforma Invoice generation record.

```python
class Invoice(UUIDTimestampedModel):
    invoice_type: CharField  # tax_invoice, proforma
    invoice_number: CharField(unique=True)
    invoice_date: DateField
    order_date: DateField
    client_name: CharField
    client_address: TextField
    client_gstin: CharField
    place_of_supply: CharField
    
    # Amount fields (in paise)
    discount_amount: IntegerField
    deductions_amount: IntegerField
    subtotal_amount: IntegerField
    net_taxable_amount: IntegerField
    tax_amount: IntegerField
    grand_total_amount: IntegerField
    
    pdf_path: CharField
    pdf_generated_at: DateTimeField
```

**Features**:
- Supports both Tax Invoice and Proforma Invoice types
- GST routing by place of supply (CGST+SGST for Telangana, IGST elsewhere)
- Automatic tax calculation
- PDF generation and storage tracking

---

#### 5. **InvoiceLineItem**
Line items within an Invoice.

```python
class InvoiceLineItem(UUIDTimestampedModel):
    invoice: ForeignKey(Invoice, related_name='line_items')
    sequence: IntegerField
    description: CharField
    hsn_sac: CharField
    quantity: IntegerField
    rate: IntegerField
    amount: IntegerField
```

---

## Services Layer (`core/services/finance.py`)

Three main service classes implement the business logic:

### 1. **BankStatementParser**

Intelligent bank statement parsing and cleaning.

**Key Methods**:
- `find_header_row()`: Skips bank logos/disclaimers, finds actual header
- `normalize_column_names()`: Maps varied column names to standard fields
- `clean_amount()`: Converts currency strings to paise (integer)
- `clean_bank_statement()`: End-to-end CSV/Excel parsing

**Example Usage**:
```python
parser = BankStatementParser()
cleaned_df = parser.clean_bank_statement('bank_statement.csv')
# Returns DataFrame with columns:
# [transaction_date, description, withdrawals, deposits, 
#  cheque_no, reference_no, entity, person, remarks, match_confidence]
```

---

### 2. **SmartTransactionMatcher**

Auto-reconciliation using keyword matching and historical lookup.

**Key Methods**:
- `apply_keyword_matching()`: Regex-based rule matching
- `apply_smart_matching()`: Combines history + keyword matching

**Default Mapping Rules**:
- `RAZORPAY|FACEBOOK` → Bold & Italic / Advertising
- `TRIPURA BIO|VUESOL` → Socialight / Client Services
- `GOOGLE|YOUTUBE|AMAZON` → Bold & Italic / Ad Spend
- `SHOPIFY` → Bold & Italic / Platform Fees

**Example Usage**:
```python
matcher = SmartTransactionMatcher()
historical_df = BankTransaction.objects.all().to_dataframe()
matched_df = matcher.apply_smart_matching(
    new_df, 
    historical_df,
    mapping_rules=None  # Uses defaults
)
# Returns DataFrame with populated entity/person/remarks and confidence scores
```

---

### 3. **ExpenseService**

Expense creation and settlement workflow.

**Key Methods**:
- `create_expense()`: Create new expense record
- `settle_expenses()`: Link multiple expenses to bank transaction

**Example Usage**:
```python
expense = ExpenseService.create_expense(
    expense_date=date.today(),
    paid_by="Abhiram",
    entity="Bold & Italic",
    amount=5000 * 100,  # ₹5000 in paise
    description="Flight booking for client",
    person="Acme Corp",
)

# Later, settle against bank transaction
reconciliations = ExpenseService.settle_expenses(
    expense_ids=[exp.id],
    bank_reference="TXN_12345",
    user=request.user
)
```

---

### 4. **InvoiceService**

Invoice generation with GST/IGST handling.

**Key Methods**:
- `calculate_taxes()`: GST routing by place of supply
- `create_invoice()`: Create invoice with line items and tax calculation

**Example Usage**:
```python
invoice = InvoiceService.create_invoice(
    invoice_type="tax_invoice",
    invoice_number="INV-26-27-001",
    invoice_date=date.today(),
    order_date=date.today(),
    client_name="Acme Corp",
    client_address="123 Business St, NY",
    client_gstin="18AABCT1234H1Z0",
    place_of_supply="maharashtra",  # Triggers IGST 18%
    line_items=[
        {
            "description": "Design Services",
            "hsn_sac": "9991",
            "quantity": 1,
            "rate": 50000 * 100,  # ₹50,000 in paise
        }
    ],
    discount_amount=500 * 100,  # ₹500 discount
)
# Returns Invoice with auto-calculated tax and grand total
```

---

## Views Layer (`core/views/finance.py`)

REST/HTML views for all financial operations:

### Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/ops/finance/` | GET | Finance dashboard with metrics |
| `/ops/finance/expenses/` | GET | List expenses with filtering |
| `/ops/finance/expenses/new/` | POST | Create new expense |
| `/ops/finance/reconciliation/` | GET/POST | Bank statement reconciliation |
| `/ops/finance/invoices/` | GET | List invoices |
| `/ops/finance/invoices/new/` | POST | Create new invoice |
| `/ops/finance/invoices/<uuid>/` | GET | View invoice details |

### View Functions

Each view includes:
- Role-based access control via `@finance_access_required` decorator
- CSRF protection
- Login requirement
- Proper error handling

---

## Admin Interface (`core/admin.py`)

Django Admin panels for all financial models:

### Registered Models
- **ExpenseAdmin**: List view with filters, search, readonly fields
- **BankTransactionAdmin**: Transaction list with confidence scoring
- **ReconciliationAdmin**: Match history and audit trail
- **InvoiceAdmin**: Invoice management with inline line items

### Features
- Full CRUD operations
- Advanced filtering (status, entity, date, confidence)
- Search across description, reference numbers, client names
- Inline editing for invoice line items
- Audit fields (created_at, updated_at, id)

---

## URL Configuration (`config/urls.py`)

Updated imports and added routes:

```python
from core.views.finance import (
    finance_dashboard,
    expense_list,
    expense_create,
    reconciliation_view,
    invoice_list,
    invoice_create,
    invoice_detail,
)

urlpatterns = [
    # ... other routes ...
    
    # Finance Management
    path("ops/finance/", finance_dashboard, name="finance-dashboard"),
    path("ops/finance/expenses/", expense_list, name="expense-list"),
    path("ops/finance/expenses/new/", expense_create, name="expense-create"),
    path("ops/finance/reconciliation/", reconciliation_view, name="reconciliation"),
    path("ops/finance/invoices/", invoice_list, name="invoice-list"),
    path("ops/finance/invoices/new/", invoice_create, name="invoice-create"),
    path("ops/finance/invoices/<uuid:invoice_id>/", invoice_detail, name="invoice-detail"),
    
    # ... webhooks ...
]
```

---

## Workflow Examples

### 1. Log & Settle Employee Expense

```python
# Step 1: Employee logs expense
expense = ExpenseService.create_expense(
    expense_date=date.today(),
    paid_by="Abhiram",
    entity="Bold & Italic",
    amount=2500 * 100,  # ₹2500
    description="Uber to client office",
)

# Step 2: Bank transaction comes in
parser = BankStatementParser()
transactions = parser.clean_bank_statement('march_statement.csv')

# Step 3: Auto-match against expense
matcher = SmartTransactionMatcher()
historical = BankTransaction.objects.all().to_dataframe()
matched = matcher.apply_smart_matching(transactions, historical)

# Step 4: User confirms match and settles
ExpenseService.settle_expenses(
    expense_ids=[expense.id],
    bank_reference="TXN_MAR_25_001",
    user=request.user
)
```

### 2. Generate Tax Invoice

```python
invoice = InvoiceService.create_invoice(
    invoice_type="tax_invoice",
    invoice_number="INV-26-27-042",
    invoice_date=date(2026, 6, 11),
    order_date=date(2026, 6, 10),
    client_name="Acme Corp",
    client_address="Bangalore, India",
    client_gstin="29AABCT1234H1Z0",
    place_of_supply="karnataka",  # IGST 18%
    line_items=[
        {
            "description": "T-Shirt Printing - Quantity 100",
            "hsn_sac": "6204",
            "quantity": 100,
            "rate": 30000,  # ₹300/unit in paise
        },
        {
            "description": "Design Consultation",
            "hsn_sac": "9991",
            "quantity": 1,
            "rate": 500000,  # ₹5000 in paise
        }
    ],
    discount_amount=100000,  # ₹1000 discount
)

# invoice.grand_total_amount = 4994000 (₹49,940 with IGST)
# PDF can be generated from invoice data
```

---

## Database Migrations

To apply the financial models to your database:

```bash
python manage.py makemigrations core
python manage.py migrate core
```

This will create the following tables:
- `core_expense`
- `core_banktransaction`
- `core_reconciliation`
- `core_invoice`
- `core_invoicelineitem`

---

## Next Steps

1. **Run Migrations**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

2. **Access Admin Interface**:
   - Navigate to `/admin/`
   - Manage expenses, transactions, and invoices

3. **Implement Frontend Templates**:
   - Create templates for `core/finance/`
   - Dashboard with charts and metrics
   - Expense form, transaction review, invoice generation

4. **Add PDF Generation**:
   - Integrate ReportLab or WeasyPrint
   - Generate PDF invoices with company branding
   - Store PDF paths in Invoice.pdf_path

5. **Role-Based Access Control**:
   - Define Finance permissions in Django
   - Implement `finance_access_required` decorator
   - Add user/group permissions in Admin

---

## Configuration Constants

From `core/services/finance.py`:

### Company Details
- Name: "Bold & Italic"
- Legal: "c/o Stoic Social LLP"
- Address: "Hyderabad, Telangana, India"
- GSTIN: "36AFEFS7497C1ZM"
- PAN: "AFEFS7497C"

### Bank Details
- Bank: "YES BANK"
- Account: "Stoic Social LLP (041363400009611)"
- IFSC: "YESB0000413"

### Employees
- Abhiram, Bubby, STC, Tarun, Vicky

---

## Comparison: Streamlit vs Django Implementation

| Feature | bold-finance (Streamlit) | BoldERP (Django) |
|---------|--------------------------|------------------|
| UI Framework | Streamlit (web app) | Django + templates/HTML |
| Database | Google Sheets | PostgreSQL/SQLite |
| Authentication | OAuth2 (Google) | Django User system |
| PDF Generation | ReportLab | ReportLab (can integrate) |
| Data Models | JSON/CSV | ORM Models |
| API | None | REST views + HTML |
| Admin | None | Django Admin |
| Type Hints | Partial | Full (Python 3.11+) |
| Transaction Safety | Limited | ACID via DB transactions |
| Audit Trail | Manual | Django audit log |

---

## Testing

Example test structure:

```python
from django.test import TestCase
from core.models import Expense, BankTransaction
from core.services.finance import ExpenseService, SmartTransactionMatcher

class ExpenseServiceTests(TestCase):
    def test_create_expense(self):
        expense = ExpenseService.create_expense(
            expense_date=date.today(),
            paid_by="Abhiram",
            entity="Bold & Italic",
            amount=5000,
        )
        self.assertEqual(expense.status, Expense.Status.PENDING)
    
    def test_settle_expense(self):
        # Create expense and bank transaction
        # Link them via settle_expenses()
        # Assert reconciliation created
        pass

class TransactionMatcherTests(TestCase):
    def test_keyword_matching(self):
        matcher = SmartTransactionMatcher()
        result = matcher.apply_keyword_matching(
            "RAZORPAY PAYMENT #12345",
            SmartTransactionMatcher.DEFAULT_MAPPING_RULES
        )
        self.assertEqual(result["entity"], "Bold & Italic")
```

---

## Support & Documentation

- **bold-finance Original Repo**: https://github.com/arcoptions/bold-finance
- **Streamlit App**: https://boldfinance.streamlit.app/Reconciliation
- **BoldERP Models**: [core/models.py](core/models.py)
- **Services**: [core/services/finance.py](core/services/finance.py)
- **Views**: [core/views/finance.py](core/views/finance.py)

