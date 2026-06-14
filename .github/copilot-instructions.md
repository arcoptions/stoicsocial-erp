# Copilot Instructions for BoldERP

## Project Context
- This repository is **BoldERP**, an internal operations platform for a print-on-demand t-shirt business.
- Technology stack:
  - Django 5.x
  - Python 3.11
  - PostgreSQL
  - Django Admin as the primary internal UI
- This app is **internal ops tooling only**. Do not write customer-facing code.

## Business Domain Scope
- Sync orders from Shopify via **inbound webhooks only**.
- Manage two inventory pools:
  - Plain blanks
  - Printed stock
- Generate print batches and Print Pack PDFs.
- Track production through a print vendor.
- Do **not** implement callbacks or outbound integrations to Shopify.
- Shiprocket handles fulfilment; do not add Shopify fulfilment callbacks.

## Coding Conventions (Mandatory)
1. Use type hints everywhere.
2. Use `transaction.atomic()` and `select_for_update()` for all stock mutations to prevent overselling.
3. Never store secrets in code; use environment variables via `django-environ`.
4. All money and quantity fields must be integers.
5. Use UUID primary keys.
6. Webhook handlers must be idempotent.
7. Follow PEP8.
8. Write docstrings on every service function.

## Backend and Data Integrity Rules
- Prioritize correctness and consistency over convenience in inventory and production flows.
- Any operation that changes stock counts must be transaction-safe and lock relevant rows.
- Ensure repeated webhook deliveries do not create duplicate side effects.
- Keep domain logic in services, not in views/admin handlers where possible.

## Assistant Behavior Expectations
- Prefer secure defaults and explicit validation.
- Preserve clear separation between webhook ingestion, domain services, and admin operations.
- When proposing schema changes, default to integer fields for currency/quantities and UUID PKs.
- Treat Django Admin workflows as the first-class operator interface.
- Avoid suggesting customer storefront features, customer notifications, or public-facing UX.
