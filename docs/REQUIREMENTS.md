# T-Shirt Ops — v1 Requirements

## Purpose
Internal tool for a Shopify print-on-demand t-shirt store to manage orders,
two inventory pools, and a printing pipeline. Single source of truth = Postgres.

## Inventory model
- BlankSKU = Fabric/GSM × Colour × Size (e.g., "Plain 180 GSM" / RED / M). Pool: plain.
- PrintedSKU = Design × Variant × Size × Colour. Pool: printed.
  - Variant covers zodiac signs, Male/Female couple sets, or null.
  - Size is nullable (non-apparel like calendars).
- Each Design has DesignAssets per colour (artwork URL + mockup URL from Google Drive,
  plus which blank fabric it consumes).

## Order flow (no split shipments)
States: new → needs_printing → in_printing → ready_to_ship → shipped → cancelled / issue.
Order status = worst-case of its line statuses (because we never split shipments).
- Soft-reserve printed stock on order create; hard-commit on shipped.
- Cancellation releases reservations.
- Bundle products (couple sets) = one OrderLine consuming multiple PrintedSKUs.

## Printing pipeline
1. Generate Print Batch: aggregate all "to_be_printed" lines across open orders by SKU,
   add buffer top-ups (target - available), check plain stock availability.
2. Confirm batch: atomically deduct plain stock, create PrintJob + PrintJobLines,
   mark linked orders "in_printing", generate Print Pack PDF (mockups + qty + QR per line).
3. Receive batch (mobile): scan/enter qty_good + qty_defective per line.
   - Auto-add exact received good qty to printed stock.
   - If received < sent → flag shortfall + auto-create ReprintTask. Manual edit allowed.
   - Release reserved plain stock. Re-evaluate linked order lines → ready_to_ship when stock suffices.

## Forecasting & buffers
- Sales velocity per PrintedSKU over rolling 7/30/90 days (from shipped orders).
- Buffer rules per PrintedSKU: min / target / max. Drives print batch top-ups and low-stock alerts.

## Integrations
- Shopify INBOUND webhooks only: orders/create, orders/updated, orders/cancelled, orders/fulfilled.
  Verify HMAC. Idempotent. No outbound to Shopify.
- Google Drive: store mockup/artwork URLs only (convert to direct-view form for PDFs).
- Alerts: ntfy.sh push + Resend email. Monitoring: Sentry.

## Users & roles
Admin / Inventory Manager / Operator / Read-only (Django groups + permissions).
Audit trail on all stock movements and key models.

## Non-functional
- Bursts up to 500 orders/day → process webhooks via background queue (Django-Q2).
- Mobile-friendly Receive screen. Desktop-first admin.
- Deploy to Railway with Postgres. Secrets via env vars.

## Deferred to v2
Customer comms, multi-warehouse, cost/margin reports, ML forecasting, vendor portal, returns/RTO, blank-stock POs.
