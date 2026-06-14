# E2E Test Cases (Frozen Requirements)

Use this checklist after running the frozen seed command.

## Prerequisite
- Run: `python manage.py seed_frozen_data --grant-roles`
- Login as a user with Inventory, Sales, and Finance access.

## Inventory Module

1. Orders Dashboard Tile Semantics
- Navigate to `/ops/inventory/orders/`
- Verify `Ready to Ship` tile is light green.
- Verify `Stale >= 3 Days` and `Urgent >= 7 Days` tiles are light red shades.
- Expected: visual urgency is clearly distinguishable.

2. Status Consistency
- On Orders list, filter `Needs Printing`.
- Check rows with `Fulfillment = fulfilled` do not appear as `Needs Printing`.
- Expected: fulfilled/in-transit/delivered rows should map to shipped-ready states, not needs printing.

3. Stale/Urgent Filters
- Click `Stale >= 3 Days` tile.
- Click `Urgent >= 7 Days` tile.
- Expected: stale subset excludes shipped/cancelled; urgent is subset of stale.

4. Order Detail Integrity
- Open any order detail page.
- Verify grouped line quantities, statuses, and totals are rendered without errors.

## Finance Module

5. Expense Filtered Unsettled Total
- Navigate to `/ops/finance/expenses/`.
- Change employee filter.
- Expected: `Total Unsettled (Filtered)` updates automatically.

6. Single Settle Mandatory Reference
- Open any pending expense.
- Click `Mark as Settled`.
- Submit without reference.
- Expected: validation error; expense remains pending.

7. Bulk Settle Same Reference
- On expense list, select multiple pending rows.
- Click `Settle Selected`.
- Enter one bank reference and submit.
- Expected: all selected expenses settle with identical `bank_reference`.

8. Reconciliation Upload and Save
- Navigate to `/ops/finance/reconciliation/`.
- Upload a bank statement sample.
- Save matched rows.
- Expected: no import errors; matched rows persist.

## Sales Module

9. Sales Dashboard Loads
- Navigate to `/ops/sales/`.
- Expected: KPI cards, top products, status mix, daily and monthly tables appear.

10. Period and Date Filters
- Change period from 90d to 30d and 7d.
- Add date range.
- Expected: KPIs and tables update for selected window.

11. Recurring and Returns Signals
- Verify recurring customer count and return/exchange signal cards are populated.
- Expected: values reflect seeded data and not blank.

12. Revenue Coverage Messaging
- Verify `Known Revenue` card displays coverage count and percentage.
- Expected: message clarifies partial payload coverage where applicable.

## Security and Access

13. Module Access Controls
- Login with a user lacking Sales role.
- Open `/ops/sales/`.
- Expected: 403 Forbidden.

14. Authorized Access
- Login with granted roles.
- Open Inventory/Sales/Finance module pages.
- Expected: all module pages accessible.

## Regression Corner Cases

15. Fulfillment-Status Mismatch Check
- Run in shell:
  `Order.objects.filter(status='needs_printing', shopify_fulfillment_status='fulfilled').count()`
- Expected: `0`.

16. Idempotent Seed Re-run
- Re-run: `python manage.py seed_frozen_data --grant-roles`
- Expected: command completes without duplicate/constraint errors.
