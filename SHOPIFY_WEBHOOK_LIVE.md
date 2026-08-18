# Shopify Webhook Setup — Live Runbook

## Current Status

**App**: https://erp.boldanditalic.in (WHM server — see [DEPLOYMENT.md](DEPLOYMENT.md) Part 10)
**Database**: SQLite at `/opt/bolderp/app/db.sqlite3`
**Webhook Endpoint**: `/webhooks/shopify/` — live, verifying HMAC, processing synchronously
**Processing**: Synchronous (immediate persistence, no worker required)
**Catch-up**: `bolderp-shopify-sync.timer` polls Shopify every 10 minutes as a backstop

### View Data

- **Orders**: https://erp.boldanditalic.in/ops/inventory/orders/
- **Print Batches**: https://erp.boldanditalic.in/ops/inventory/print-batches/
- **Webhook events**: https://erp.boldanditalic.in/ops/inventory/webhook-events/
- **Designs (admin)**: https://erp.boldanditalic.in/admin/core/design/

---

## Shopify Integration Setup

### Step 1: Create the Shopify App

1. Log in to Shopify Admin: https://admin.shopify.com
2. Go to **Settings → Apps and Integrations → Develop apps**
3. Click **Create an app**:
   - Name: "BoldERP Production"
   - Type: Custom app (for internal use)
4. In **Configuration → Admin API integration**, enable scopes:
   - `read_orders`
   - `write_orders`
5. Install the app and copy the **Admin API access token** (`shpat_…`). The catch-up sync needs
   it; webhooks do not.

### Step 2: Configure Webhooks in Shopify

Shopify Admin → **Settings → Notifications → Webhooks** (store-level), or the app's
**Configuration → Webhooks** if you subscribed through the app.

| Shopify UI label | Actual topic | URL |
|---|---|---|
| Order creation | `orders/create` | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Order update | `orders/updated` | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Order cancellation | `orders/cancelled` | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Order fulfillment | `orders/fulfilled` | `https://erp.boldanditalic.in/webhooks/shopify/` |

Format **JSON**, API version **2025-01** or later.

> ⚠️ **"Order edit" is not "Order update".** The Shopify label *Order edit* is the topic
> `orders/edited`, which BoldERP does **not** handle — it is dropped with a 200. The one you
> want is *Order update* = `orders/updated`. Subscribing to the wrong one looks correct in the
> Shopify UI and silently does nothing.

Only these four topics are processed (`core/services/shopify.py`). Anything else is accepted,
logged as a `WebhookEvent`, and ignored.

Copy the **signing secret** shown on the webhooks page — all webhooks on a store share one.

### Step 3: Set the server environment variables

`.env` lives at `/opt/bolderp/app/.env` and is loaded by systemd via `EnvironmentFile=`. Edit it
**in place** — never restore it from git, because the repo has an empty `.gitignore` and the
committed `.env` is a stale snapshot.

```bash
ssh bolderp
sudo cp /opt/bolderp/app/.env /opt/bolderp/runtime/backups/env-$(date +%Y%m%d-%H%M%S).bak
sudo -u bolderp nano /opt/bolderp/app/.env
```

```ini
SHOPIFY_API_SECRET=<signing secret from the Webhooks page>   # webhooks
SHOPIFY_SHOP_DOMAIN=c0c416-77.myshopify.com                  # catch-up sync
SHOPIFY_ADMIN_API_TOKEN=shpat_...                            # catch-up sync
SHOPIFY_API_VERSION=2025-01                                  # optional
```

```bash
sudo systemctl restart bolderp     # env is only re-read on restart
```

Verify the secret matches Shopify without printing it:

```bash
sudo -u bolderp /opt/bolderp/venv/bin/python -c "
import django, os, hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from django.conf import settings
print(hashlib.sha256(settings.SHOPIFY_API_SECRET.encode()).hexdigest()[:12])"
```

Compare that prefix with the sha256 of the secret in Shopify Admin. Equal → the secret is right.

---

## Testing Webhook Delivery

```bash
# Local (dev server must be running)
python test_webhook_delivery.py \
  --url http://localhost:8000/webhooks/shopify/ \
  --secret "your-local-secret"

# Production
python test_webhook_delivery.py \
  --url https://erp.boldanditalic.in/webhooks/shopify/ \
  --secret "your-shopify-signing-secret"
```

**Success (200 OK)**
```json
{ "processed": true, "event_id": "47539e47-a4e0-487b-bfb2-5fce0648b09d" }
```

**HMAC failure (401)** — `{"detail": "Invalid signature"}`. Note that a 401 is also the *correct*
response to a deliberately-bad signature, so it is a useful liveness probe: if the endpoint
returns 401 rather than 404/502, routing and TLS are fine and only the secret is in question.

### Shopify's "Send test notification" button

Each webhook row has its own button and fires **only that one topic** — clicking it on
*Order creation* does not test *Order update*. The sample payload uses order id
`820982911946154508`, which does not exist in the ERP, so:

- `orders/create` / `orders/updated` → ingested as a real order (delete it afterwards)
- `orders/cancelled` / `orders/fulfilled` → a no-op, because there is no such local order

A test notification therefore proves **routing, TLS and HMAC**, not ingestion. Confirm delivery
on the [webhook events page](https://erp.boldanditalic.in/ops/inventory/webhook-events/).

---

## Webhook Behavior

### How orders flow

1. **Shopify → BoldERP** — POST to `/webhooks/shopify/`, HMAC verified, order persisted,
   200 returned immediately.
2. **Order matching** — line items matched by design name + colour + size (or a stored
   `ProductNameAlias`). Printed stock available → `ready_ship`; otherwise → `to_be_printed`.
   No design match → the line lands in **Unmatched Orders** on the Print Batches page.
3. **Status propagation** — order status is the worst-case line status:
   new → needs_printing → in_printing → ready_to_ship → shipped.

### Idempotency

Each webhook carries a unique `idempotency_key` (the Shopify webhook id) and `ingest_order`
upserts on `shopify_order_id`. Duplicate deliveries and re-runs of the catch-up sync are no-ops.

### Event tracking

Every **accepted** webhook is written to `WebhookEvent` (`source`, `topic`, `idempotency_key`,
`payload`, `processed_at`). Rejected ones are not — see the note under Common Errors.

```bash
ssh bolderp
cd /opt/bolderp/app
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py shell -c "
from core.models import WebhookEvent
print(WebhookEvent.objects.filter(source='shopify').count())
print(list(WebhookEvent.objects.values('topic','processed_at').order_by('-processed_at')[:10]))"
```

**If that count is 0, no webhook has ever reached this server** — the subscription is missing or
points somewhere else. That is the single most diagnostic number in this document.

---

## Catch-Up Sync (when webhooks miss orders)

Webhooks are the primary path, but they fail silently: if the subscription is deleted, points at
a dead URL, or `SHOPIFY_API_SECRET` drifts from the signing secret, the delivery is rejected
**before** a `WebhookEvent` row is written. Nothing appears in the events table — the only
symptom is that orders stop arriving. **Shopify never replays webhooks it failed to deliver**, so
any outage window has to be closed by a sync.

### Step 1 — Read the sync-health banner

The Orders page (`/ops/inventory/orders/`) shows a banner above the stat cards: last webhook
received, count in the last 24 hours, newest order in the ERP. No webhook in 24 hours turns it
red. Start there — it tells you within seconds whether deliveries stopped, and when.

### Step 2 — Confirm the subscription in Shopify

Shopify Admin → **Settings → Notifications → Webhooks**. Confirm the four topics above exist and
point at `https://erp.boldanditalic.in/webhooks/shopify/`. A stale URL from an old host is the
most likely cause and looks perfectly healthy in the UI. You can also list them from the API:

```bash
curl -s -H "X-Shopify-Access-Token: $SHOPIFY_ADMIN_API_TOKEN" \
  "https://c0c416-77.myshopify.com/admin/api/2025-01/webhooks.json" \
  | python -m json.tool
```

### Step 3 — Pull in whatever was missed

Back up the database first — the sync writes orders and, with `--apply-inventory`, moves stock.

```bash
ssh bolderp
cd /opt/bolderp/app

sudo -u bolderp /opt/bolderp/venv/bin/python -c "
import sqlite3; s=sqlite3.connect('db.sqlite3')
d=sqlite3.connect('/opt/bolderp/runtime/backups/db-$(date +%Y%m%d-%H%M%S).sqlite3')
s.backup(d); d.close(); s.close()"

# Dry run first: fetch and count, write nothing.
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py sync_shopify_orders \
  --since-minutes 1440 --dry-run

# Then for real, behaving exactly like a live webhook (reserves printed stock).
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py sync_shopify_orders \
  --since-minutes 1440 --apply-inventory

# Or from an exact instant, which overrides --since-minutes.
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py sync_shopify_orders \
  --updated-at-min 2026-08-16T00:00:00Z --apply-inventory
```

| Flag | Effect |
|------|--------|
| `--since-minutes N` | Only orders Shopify updated in the last N minutes |
| `--updated-at-min ISO` | Same, from an exact ISO-8601 timestamp; overrides `--since-minutes` |
| `--apply-inventory` | Reserve printed stock as a webhook would. **Omit for a full historical backfill** |
| `--dry-run` | Fetch and count only; no DB writes |
| `--shop-domain` / `--access-token` / `--api-version` | Override the `.env` values for a one-off run |

The command reports `created` and `updated` separately. Re-running it is safe: `ingest_order`
upserts on `shopify_order_id`.

> Historical orders imported before Aug 2026 carry the date BoldERP imported them in
> `created_at`. Migration `0008` recovers the real Shopify dates from each order's stored
> `raw_payload` into `shopify_created_at`, which is what the dashboard sorts and filters on.

### Step 4 — The automatic poll

A systemd timer runs the same catch-up every 10 minutes, so a dropped delivery self-heals.

```bash
systemctl status  bolderp-shopify-sync.timer
systemctl list-timers 'bolderp*'
journalctl -u bolderp-shopify-sync --since "-1h" --no-pager
sudo systemctl start bolderp-shopify-sync.service    # run one now, on demand
```

Unit files live at `/etc/systemd/system/bolderp-shopify-sync.{service,timer}` and are reproduced
in [DEPLOYMENT.md](DEPLOYMENT.md). Each run looks back 30 minutes — 3× the interval — so a slow
run cannot leave a gap.

> **Do not use `core.tasks.schedule_shopify_catch_up()`.** It creates a Django-Q `Schedule` row,
> and there is **no `qcluster` worker service on this server** — the row is created and never
> fires. The systemd timer above is the real mechanism. The Django-Q function is kept only for
> environments that do run a worker.

The poll reads `SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ADMIN_API_TOKEN` and optionally
`SHOPIFY_API_VERSION` from `.env`. If any are missing it logs a warning and returns zero counts
rather than failing.

---

## Troubleshooting

### Webhooks not being processed

0. **Check the sync-health banner** on `/ops/inventory/orders/` — last webhook received and how
   long ago.

1. **Count `WebhookEvent` rows** (command under [Event tracking](#event-tracking)). Zero means
   nothing has ever arrived — go straight to the Shopify subscription URL.

2. **Check Shopify webhook status** — Shopify Admin → Settings → Notifications → Webhooks. Red ❌
   or ⚠️ status codes, and the URL each one points at.

3. **Check the server logs**:
   ```bash
   ssh bolderp
   journalctl -u bolderp --since "-1h" --no-pager | grep -i webhook
   journalctl -u bolderp --since "-1h" --no-pager | grep -i "invalid signature"
   ```

4. **Verify the secret** — the sha256-prefix command in Step 3 above.

5. **Test the endpoint directly** — `python test_webhook_delivery.py --url ... --secret ...`
   should return 200 with `"processed": true`.

### Common errors

**"Invalid signature" (401)**
- `SHOPIFY_API_SECRET` doesn't match Shopify's signing secret
- Fix: update `/opt/bolderp/app/.env` and `sudo systemctl restart bolderp`
- Rejected deliveries are **not** written to `WebhookEvent` (the endpoint is public, so logging
  unauthenticated POSTs would grow the table without bound). They appear only in
  `journalctl -u bolderp` as a warning, and as silence on the Orders sync banner.

**Webhooks show delivered in Shopify but nothing in the ERP**
- Almost always a stale URL on the subscription pointing at a decommissioned host. Shopify shows
  the delivery as attempted against whatever URL is configured.

**Orders arriving but showing as unmatched**
- The Shopify product title doesn't match any Design in the ERP
- Fix: Print Batches page → "Unmatched Orders" table → link to an existing Printed SKU or create
  the missing one. Leave **Remember this name** ticked and a `ProductNameAlias` is stored, so
  every future order with that title matches on its own.

**"SKU is not a valid UUID" (500)**
- Test payload has an invalid SKU format. Webhooks match by design name, not SKU — leave it empty.

**Order not created despite 200 OK**
- Idempotency: the order already exists. Check with the shell command above.

**502 Bad Gateway**
- Gunicorn is down or restarting: `sudo systemctl status bolderp` and
  `journalctl -u bolderp -n 100 --no-pager`.
- `curl 127.0.0.1:8010` returning **400** is not a fault — `ALLOWED_HOSTS` rejects the bare IP.
  Test against the public hostname.

---

## Commands Reference

All server commands assume `ssh bolderp && cd /opt/bolderp/app`.

```bash
PY=/opt/bolderp/venv/bin/python

# Recent orders by real Shopify order date, not import date
sudo -u bolderp $PY manage.py shell -c "from core.models import Order; print(list(Order.objects.order_by('-shopify_created_at')[:5]))"

# Catch up on anything webhooks missed in the last day
sudo -u bolderp $PY manage.py sync_shopify_orders --since-minutes 1440 --apply-inventory

# Webhook event count
sudo -u bolderp $PY manage.py shell -c "from core.models import WebhookEvent; print(WebhookEvent.objects.filter(source='shopify').count())"

# Catch-up timer
systemctl list-timers 'bolderp*'
journalctl -u bolderp-shopify-sync --since "-1d" --no-pager

# App logs
journalctl -u bolderp -f

# Deploy (from your machine, after pushing to main)
./deploy.sh
```

---

## Architecture

```
Shopify Admin
    ↓
    ├→ POST /webhooks/shopify/          (primary path, real time)
    │   (HMAC verification — a 401 here writes nothing to the DB)
    │       ↓
    └→ bolderp-shopify-sync.timer → manage.py sync_shopify_orders
        (catch-up path, polls updated_at_min — same ingest, same result)
            ↓
        core/services/shopify.py
            ├→ ingest_order()           (upsert on shopify_order_id)
            ├→ mark_cancelled()
            └→ sync_fulfillment()
            ↓
        Database (Orders, OrderLines, WebhookEvents, ProductNameAlias)
            ↓
        Inventory System
        (reserve_printed, release_printed, commit_printed)
            ↓
        Print Batches, Pick Lists, etc.
```

---

**Last Updated**: 2026-08-18
**See also**: [DEPLOYMENT.md](DEPLOYMENT.md) Part 10 for the server layout and deploy procedure
