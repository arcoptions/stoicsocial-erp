with open('config/urls.py', 'r') as f:
    content = f.read()

# Add new finance URLs before the webhooks section
insert_point = content.find("    # Webhooks")
if insert_point > 0:
    new_finance_urls = """
    # Finance Management
    path("ops/finance/expenses/", expense_list, name="expense-list"),
    path("ops/finance/expenses/new/", expense_create, name="expense-create"),
    path("ops/finance/reconciliation/", reconciliation_view, name="reconciliation"),
    path("ops/finance/invoices/", invoice_list, name="invoice-list"),
    path("ops/finance/invoices/new/", invoice_create, name="invoice-create"),
    path("ops/finance/invoices/<uuid:invoice_id>/", invoice_detail, name="invoice-detail"),
"""
    content = content[:insert_point] + new_finance_urls + "\n    " + content[insert_point:]

with open('config/urls.py', 'w') as f:
    f.write(content)

print("Finance URLs added successfully!")
