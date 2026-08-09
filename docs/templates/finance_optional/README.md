# Optional Finance Opening Data

These files capture finance opening data requirements. They are reference/input templates and are not imported by `import_production_csv_bundle`.

Use ISO dates (`YYYY-MM-DD`). All money fields are integer paise, never decimal rupees.

- `expenses.csv`: Status must be `pending`, `settled`, or `rejected`.
- `bank_transactions.csv`: Confidence must be `auto_reconciled`, `needs_review`, or `manual_matched`.
- `invoices.csv`: Type must be `tax_invoice` or `proforma`; place of supply must be `telangana`, `maharashtra`, `karnataka`, `delhi`, or `others`.
- `invoice_line_items.csv`: `invoice_number` must match a row in `invoices.csv`; quantity is an integer and rate is paise.

Provide these only when historical finance opening data must be migrated. New finance records can instead be entered through the ERP finance workflows.
