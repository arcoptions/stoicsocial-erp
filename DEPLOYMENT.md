# BoldERP Local Development & Deployment Guide

## Prerequisites

- Python 3.11+
- PostgreSQL 13+ (or SQLite for local dev)
- Git
- pip (Python package manager)
- Virtual environment tool (venv or virtualenv)

## Part 1: Local Development Setup

### Step 1: Clone & Initialize the Repository

```bash
# Navigate to your workspace
cd c:\Users\abhiramnarla\stoicsocial-erp

# Create a Python virtual environment
python -m venv venv

# Activate the virtual environment
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# On Windows (Command Prompt):
venv\Scripts\activate.bat

# On macOS/Linux:
source venv/bin/activate
```

### Step 2: Set Up Environment Variables

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your local values (use a text editor)
# For local development, you can use minimal settings:
```

Minimal `.env` for local testing:
```
DJANGO_SECRET_KEY=your-local-secret-key-12345
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
SHOPIFY_API_SECRET=test-secret-key-local
INTERNAL_API_TOKEN=test-internal-token-local
# Leave these empty for local dev (optional, used only if real values provided):
NTFY_TOPIC=
RESEND_API_KEY=
SENTRY_DSN=
```

### Step 3: Install Dependencies

```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install all requirements
pip install -r requirements.txt
```

### Step 4: Run Database Migrations

```bash
# Apply Django migrations
python manage.py migrate

# Create a superuser for Django Admin
python manage.py createsuperuser
# Follow the prompts to create your admin account
```

### Step 5: Collect Static Files

```bash
python manage.py collectstatic --noinput
```

### Step 6: Start the Development Server

```bash
python manage.py runserver
```

Output should show:
```
Starting development server at http://127.0.0.1:8000/
Press CTRL+C to quit.
```

### Step 7: Access the Application

- **Django Admin**: http://localhost:8000/admin/
  - Login with the superuser credentials you created in Step 4
  - You can browse models here

- **Print Batches**: http://localhost:8000/ops/print-batches/
- **Receive Dashboard**: http://localhost:8000/ops/receive/
- **Forecast**: http://localhost:8000/ops/forecast/

---

## Part 2: Bootstrap Master Data

### Import Vendors, Designs, and Inventory

You need an Excel workbook with the following sheets:
- `vendors`
- `designs`
- `design_assets`
- `blank_skus`
- `printed_skus`

Example Excel structure:

**vendors sheet:**
| name | contact | is_active |
|------|---------|-----------|
| PrintCo | contact@printco.com | 1 |

**designs sheet:**
| product_type | sub_category | variants | notes |
|--------------|--------------|----------|-------|
| T-Shirt | Basic | ["S", "M", "L"] | Basic crew neck |

**blank_skus sheet:**
| fabric | colour | size | on_hand | reserved | reorder_min | reorder_target |
|--------|--------|------|---------|----------|-------------|-----------------|
| Cotton | White | M | 100 | 0 | 20 | 50 |

**Run the importer:**

```bash
# Open Django shell
python manage.py shell

# Run the importer
from importer import run, print_summary
result = run(r'C:\path\to\your\workbook.xlsx', dry_run=False)
print_summary(result)
```

Expected output:
```
Imported Summary:
- Vendors: 5
- Designs: 12
- Design Assets: 24
- Blank SKUs: 48
- Printed SKUs: 144
```

---

## Part 3: Run Async Tasks (Django-Q2)

### Terminal 1: Keep the web server running
```bash
python manage.py runserver
```

### Terminal 2: Start the task queue worker

```bash
# Activate the same virtual environment in a new terminal
.\venv\Scripts\Activate.ps1

# Run the Django-Q2 cluster
python manage.py qcluster
```

Output should show:
```
15:30:45 [Q] INFO: Starting Django Q Cluster
15:30:45 [Q] INFO: No previous cluster configuration. Creating one...
15:30:45 [Q] INFO: 4 workers started
```

### Test Low-Stock Alerts

Once the worker is running, you can trigger the low-stock check:

```bash
# From the Django shell (Terminal 3)
python manage.py shell

# Manually trigger the task
from core.tasks import low_stock_check
low_stock_check()
```

---

## Part 4: Test Shopify Webhook Ingestion

### Setup ngrok (for local webhook testing)

```bash
# Install ngrok (if not already installed)
# Download from https://ngrok.com/download or use: choco install ngrok

# Start ngrok tunnel pointing to your local Django server
ngrok http 8000
```

You'll see output like:
```
Forwarding http://abcd1234.ngrok.io -> http://localhost:8000
```

### Configure Shopify Test Webhook

1. In Shopify Admin: Settings → Apps and integrations → Webhooks
2. Create a test webhook:
   - Event: `orders/created`
   - URL: `http://abcd1234.ngrok.io/webhooks/shopify/`
   - Keep the webhook secret safe

3. Update your `.env`:
```
SHOPIFY_API_SECRET=your-actual-shopify-secret-from-the-webhook-setup
```

### Test with Sample Payload

```bash
# Terminal 3: Use curl or Python to send a test webhook

# Option A: Using Python requests
python << 'EOF'
import requests
import json
from core.services.shopify import verify_hmac
import base64
import hmac
import hashlib

# Sample order payload
payload = {
    "id": 123456789,
    "email": "test@example.com",
    "name": "#1001",
    "line_items": [
        {
            "id": 987654321,
            "product_id": 123,
            "title": "Custom T-Shirt",
            "variant_title": "Red / M",
            "quantity": 2
        }
    ]
}

secret = "your-shopify-api-secret"
body = json.dumps(payload)

# Generate HMAC signature
h = hmac.new(
    secret.encode(),
    body.encode(),
    hashlib.sha256
)
signature = base64.b64encode(h.digest()).decode()

# Send webhook
headers = {
    "X-Shopify-Hmac-SHA256": signature,
    "Content-Type": "application/json",
    "X-Shopify-Topic": "orders/created"
}

response = requests.post(
    "http://localhost:8000/webhooks/shopify/",
    data=body,
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
EOF
```

### Check if Order was Created

```bash
# Terminal 3: Django shell
python manage.py shell

from core.models import Order, OrderLine
# Check the latest order
orders = Order.objects.all().order_by('-created_at')
if orders:
    order = orders[0]
    print(f"Order: {order.order_no}")
    print(f"Lines: {order.orderline_set.count()}")
```

---

## Part 5: Test Print Batch Workflow

### Step 1: Create Test Orders

Use the webhook test from Part 4 to create orders with various printed SKUs.

### Step 2: Visit Print Batch Suggestion

Navigate to: http://localhost:8000/ops/print-batches/

You should see:
- Table showing all pending orders grouped by PrintedSKU
- Demand quantities
- Buffer top-up recommendations
- Available blank SKU inventory

### Step 3: Confirm a Batch

1. Select a vendor from the dropdown
2. The system shows recommended quantities (demand + buffer)
3. You can edit quantities before confirming
4. Click "Confirm Batch"
5. System should:
   - Create a PrintBatch
   - Create a PrintJob
   - Deduct inventory
   - Mark orders as IN_PRINTING
   - Generate a PDF (check `/media/print_packs/`)

### Step 4: Download Print Pack PDF

After confirmation, you'll see a success message with a link to the PDF. The PDF should contain:
- Job header (ID, vendor, date)
- Table with:
  - Design/variant/color/size
  - Quantity
  - Mockup images (if available)
  - QR codes (encoded as base64 data URIs)

---

## Part 6: Test Inventory Management

### Check BlankSKU and PrintedSKU

```bash
python manage.py shell

from core.models import BlankSKU, PrintedSKU, StockMovement

# View blank SKU inventory
blank = BlankSKU.objects.first()
print(f"SKU: {blank.fabric} / {blank.colour} / {blank.size}")
print(f"On Hand: {blank.on_hand}, Reserved: {blank.reserved}, Available: {blank.available}")

# View stock movements (audit trail)
movements = StockMovement.objects.all().order_by('-created_at')[:5]
for m in movements:
    print(f"{m.reason}: {m.delta_on_hand} on_hand, {m.delta_reserved} reserved")
```

### Manual Stock Adjustment (Admin)

In Django Admin:
1. Go to /admin/core/blanksku/
2. Click on a SKU
3. Use "Stock Management" or direct field edits
4. Save (a StockMovement audit record is created automatically)

---

## Part 7: Test Forecast View

Navigate to: http://localhost:8000/ops/forecast/

You should see:
- All PrintedSKU with sales velocity
- 7-day, 30-day, 90-day unit counts
- Current available stock
- Days of stock calculation
- Risk highlights (red background) for low inventory

---

## Part 8: Test Receive Workflow

Navigate to: http://localhost:8000/ops/receive/

1. Shows all IN_PRODUCTION orders
2. Click an order line to mark quantities received
3. Enter:
   - Quantity received (good)
   - Quantity defective
4. System marks order as RECEIVED if all lines complete

---

## Part 9: Run Tests & Validate Code

### Run Django Tests

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test core

# Run with verbose output
python manage.py test --verbosity=2
```

### Check Code Quality

```bash
# Format code with black
pip install black
black core/ config/

# Lint with flake8
pip install flake8
flake8 core/ config/

# Type check with mypy
pip install mypy
mypy core/
```

---

## Part 10: Production Deployment (WHM server)

Production is a WHM/cPanel box serving `https://erp.boldanditalic.in`. There is **no Railway,
no Docker and no CI/CD** — deployment is a git pull over SSH followed by a service restart.

| | |
|---|---|
| SSH | `ssh bolderp` (alias in `~/.ssh/config` → `132.148.130.26`, user `bolderp-agent`) |
| Project | `/opt/bolderp/app` |
| Virtualenv | `/opt/bolderp/venv` |
| Runs as | user/group `bolderp` |
| Service | `bolderp.service` (systemd) |
| App server | gunicorn `config.wsgi:application` on `127.0.0.1:8010`, 3 workers |
| Reverse proxy | Apache terminates TLS and forwards to gunicorn |
| Database | **SQLite** at `/opt/bolderp/app/db.sqlite3` |
| Env file | `/opt/bolderp/app/.env` (read by systemd via `EnvironmentFile=`) |

### Deploying

From your machine, push to `main` first. Then:

```bash
./deploy.sh
```

`deploy.sh` performs the whole sequence and refuses to continue if the incoming commits
touch `db.sqlite3`, `.env` or `media/`. To do it by hand:

```bash
ssh bolderp
cd /opt/bolderp/app

# 1. Back up the live DB first (sqlite online-backup API — safe while running)
sudo -u bolderp /opt/bolderp/venv/bin/python -c "
import sqlite3; s=sqlite3.connect('db.sqlite3')
d=sqlite3.connect('/opt/bolderp/runtime/backups/db-$(date +%Y%m%d-%H%M%S).sqlite3')
s.backup(d); d.close(); s.close()"

# 2. Fetch — the explicit refspec is REQUIRED (see below)
sudo -u bolderp git fetch origin "+refs/heads/main:refs/remotes/origin/main"
sudo -u bolderp git merge origin/main

# 3. Apply and restart
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py migrate
sudo -u bolderp /opt/bolderp/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart bolderp

# 4. Verify
curl -s -o /dev/null -w "%{http_code}\n" https://erp.boldanditalic.in/   # expect 302
journalctl -u bolderp --since "-5m" --no-pager | grep -i error
```

### ⚠ Never use `git reset --hard` or `git checkout -- .` on the server

`.gitignore` is empty in this repo, so `.env`, `db.sqlite3`, `media/` and `staticfiles/` are
all **committed**. Any command that restores tracked files from a commit will overwrite the
live production database and the production secrets with a stale snapshot. Use `git merge`
only. The server's working tree shows `.env` and `db.sqlite3` as permanently modified — that
is normal here, not a problem to "clean up".

### Gotchas that will cost you time

1. **`git fetch origin main` does not update `refs/remotes/origin/main`.** It only moves
   `FETCH_HEAD`, so `origin/main` looks stale and the merge is a no-op. Always pass the
   explicit refspec shown above.
2. **`python3` is not on PATH** on this box. Always use `/opt/bolderp/venv/bin/python`.
3. **The server carries local commits** that duplicate upstream ones, so merges can conflict
   on files that are byte-identical upstream. Verify with
   `git diff <server-commit> <upstream-commit> -- <file>`; if the diff is empty, resolve with
   `git checkout origin/main -- <file>`.
4. **`curl 127.0.0.1:8010` returns 400.** That is `ALLOWED_HOSTS` rejecting the bare IP, not a
   failure. Verify against the public hostname instead.

### Scheduled jobs

There is no `qcluster` worker service, so Django-Q `Schedule` rows never fire. Recurring work
runs from the `bolderp` user's crontab instead:

```bash
sudo -u bolderp crontab -l                        # what is scheduled
tail -f /opt/bolderp/logs/shopify-sync.log        # last catch-up sync runs
```

The only job today is the Shopify catch-up sync, every 10 minutes. See
[deploy/README.md](deploy/README.md) — including how to switch it to a systemd timer, which is
preferable but needs root.

### Sudo on the deploy account

`bolderp-agent` has `NOPASSWD: ALL` **as the `bolderp` user**, but its root rights are scoped to
four commands: `systemctl status|is-active|restart bolderp` and `journalctl -u bolderp *`.
So `sudo mkdir`, `sudo systemctl daemon-reload` and installing unit files all fail. Anything
that needs to touch `/etc` requires a real root login. Prefix ordinary work with
`sudo -u bolderp`, and note that `systemctl is-active` and `journalctl` also work with no sudo
at all.

### Rollback

Restore the most recent backup from `/opt/bolderp/runtime/backups/` over `db.sqlite3` and
restart the service. Do not roll back code with `git reset --hard` — check out the previous
commit's source files explicitly, or merge a revert commit.

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'core'"

**Solution:**
```bash
# Make sure you're in the project root directory
cd c:\Users\abhiramnarla\stoicsocial-erp

# Reinstall in editable mode
pip install -e .
```

### Issue: "Database does not exist"

**Solution:**
```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

### Issue: Migrations not applied

**Solution:**
```bash
# Check migration status
python manage.py showmigrations

# Apply all pending migrations
python manage.py migrate --run-syncdb
```

### Issue: Static files not loading

**Solution:**
```bash
# Collect static files
python manage.py collectstatic --noinput --clear

# In settings.py, ensure DEBUG=True for local dev or use whitenoise
```

### Issue: Webhook signature verification fails

**Solution:**
- Verify `SHOPIFY_API_SECRET` matches the webhook secret from Shopify Admin
- Ensure the request body hasn't been modified before signature verification
- Check that headers include `X-Shopify-Hmac-SHA256`

### Issue: Django-Q2 worker not picking up tasks

**Solution:**
```bash
# Stop the worker and restart
python manage.py qcluster

# Check the Q Cluster admin interface at /admin/django_q/task/
```

### Issue: WeasyPrint error on Windows: "cannot load library 'gobject-2.0-0'"

**Cause:** WeasyPrint requires GTK system libraries which aren't installed on Windows development machines.

**Solutions (choose one):**

1. **Recommended: skip PDF generation locally.** The WeasyPrint import is lazy-loaded, so
   migrations, tests and every other command work fine on Windows. Only the print-pack PDF
   download itself fails. Confirming a batch still creates the PrintBatch, PrintJob, stock
   movements and order status changes — only the PDF render step errors.

2. **Install the GTK runtime** (needed if you must render PDFs on Windows):
   - Install the MSYS2 GTK3 runtime, or the standalone
     [gtk3-runtime Windows installer](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
   - Add its `bin` directory to `PATH`, then restart your shell so Python can find
     `libgobject-2.0-0.dll`
   - Full instructions: https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows

3. **Verify on the server instead.** Production is Linux and has the GTK libraries, so PDF
   generation works there. Push, deploy, and download a print pack from
   `https://erp.boldanditalic.in/ops/print-batches/`.

> There is no Dockerfile in this repo — it was removed along with the rest of the Railway
> tooling. Don't reach for `docker build`; it will not find one.

---

### Issue: PostgreSQL connection error

**Solution:**
```bash
# Use SQLite for local development instead
# In .env, use: DATABASE_URL=sqlite:///db.sqlite3

# Or install and start PostgreSQL locally
# Then verify connection string in DATABASE_URL
```

---

## Quick Reference: File Locations

| Component | Location |
|-----------|----------|
| Models | `core/models.py` |
| Services | `core/services/` |
| Views | `core/views/` |
| Tasks | `core/tasks.py` |
| Templates | `core/templates/` |
| Settings | `config/settings.py` |
| URLs | `config/urls.py` |
| Requirements | `requirements.txt` |
| Static Files | `staticfiles/` |
| Media Files | `media/` |
| Database | `db.sqlite3` (SQLite) or remote PostgreSQL |

---

## Success Checklist

- [ ] Virtual environment activated
- [ ] Dependencies installed (`pip list | grep django`)
- [ ] `.env` file configured
- [ ] Database migrations applied
- [ ] Superuser created
- [ ] Dev server running on localhost:8000
- [ ] Django Admin accessible
- [ ] Master data imported (vendors, designs, SKUs)
- [ ] Print batch workflow tested
- [ ] Orders created and processed
- [ ] Forecast view showing data
- [ ] Django-Q2 worker running (in separate terminal)
- [ ] Low-stock alerts triggered

---

## Next Steps

1. **Development**: Edit code, test locally, commit to git
2. **Testing**: Run `python manage.py test` before pushing
3. **Deployment**: Push to `main`, then run `./deploy.sh` (see Part 10)
4. **Monitoring**: `journalctl -u bolderp -f` on the server; webhook health is on the Orders
   page banner and at `/ops/inventory/webhook-events/`
