# BoldERP Production Setup Guide

## Overview
This guide walks through setting up BoldERP from scratch with your master data, making it fully functional and production-ready.

---

## Phase 1: Database Initialization (5 minutes)

### Step 1: Verify Virtual Environment
```bash
# In PowerShell:
.\venv\Scripts\Activate.ps1

# You should see (venv) in your prompt
```

### Step 2: Verify `.env` Configuration
Create or update `c:\Users\abhiramnarla\stoicsocial-erp\.env`:

```env
DJANGO_SECRET_KEY=your-secret-key-change-this-in-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
SHOPIFY_API_SECRET=test-secret-key-local
INTERNAL_API_TOKEN=test-internal-token-local
NTFY_TOPIC=
RESEND_API_KEY=
SENTRY_DSN=
```

### Step 3: Create Database Tables
```bash
cd c:\Users\abhiramnarla\stoicsocial-erp

# Create all tables from models
python manage.py migrate

# Expected output:
# Operations to perform:
#   Apply all migrations: admin, auth, contenttypes, core, django_q, ...
# Running migrations:
#   Applying contenttypes.0001_initial... OK
#   ...
```

### Step 4: Create Django Superuser
```bash
python manage.py createsuperuser

# Follow prompts:
# Username: admin
# Email address: admin@localhost
# Password: (choose something secure)
```

### Step 5: Collect Static Files
```bash
python manage.py collectstatic --noinput
```

---

## Phase 2: Import Master Data (10 minutes)

Your Excel file needs these sheets with these exact column headers:

### Sheet 1: `vendors`
| name | contact | is_active |
|------|---------|-----------|
| PrintCo | contact@printco.com | 1 |

### Sheet 2: `designs`
| product_type | sub_category | variants | notes |
|--------------|--------------|----------|-------|
| T-Shirt | Basic | ["S", "M", "L"] | Design notes here |

**Note:** `variants` can be:
- JSON array: `["S", "M", "L"]`
- Comma-separated: `S, M, L`

### Sheet 3: `design_assets`
| design_product_type | design_sub_category | colour | artwork_url | mockup_url | blank_fabric |
|--------|---------|--------|----------|----------|----------|
| T-Shirt | Basic | Red | https://... | https://... | Cotton |

**Note:** Reference the design by product_type + sub_category combination

### Sheet 4: `blank_skus`
| fabric | colour | size | on_hand | reserved | reorder_min | reorder_target |
|--------|--------|------|---------|----------|-------------|-----------------|
| Cotton | Red | M | 100 | 0 | 20 | 50 |
| Cotton | Red | L | 80 | 0 | 20 | 50 |

### Sheet 5: `printed_skus`
| design_product_type | design_sub_category | variant | colour | size | on_hand | reserved | buffer_min | buffer_target | buffer_max |
|--------|---------|---------|---------|------|---------|----------|------------|----------|----------|
| T-Shirt | Basic | S | Red | M | 50 | 0 | 10 | 30 | 100 |

**Note:** Leave variant/size blank if design doesn't have them

### Step 1: Prepare Your Excel File

Rename your "Master Order Tracker (1).xlsx" to "master_data.xlsx" and ensure it has all 5 sheets listed above with correct column headers.

**Test the structure first:**
```bash
# Open Django shell
python manage.py shell

# Check if Excel is readable
import openpyxl
wb = openpyxl.load_workbook(r'C:\path\to\master_data.xlsx')
print(wb.sheetnames)
# Should output: ['vendors', 'designs', 'design_assets', 'blank_skus', 'printed_skus']
```

### Step 2: Run the Importer

```bash
python manage.py shell
```

Then inside the shell:
```python
from importer import run, print_summary

# Dry run first (doesn't commit to database)
result = run(r'C:\path\to\master_data.xlsx', dry_run=True)
print_summary(result)

# If all counts look correct, run for real
result = run(r'C:\path\to\master_data.xlsx', dry_run=False)
print_summary(result)
```

Expected output:
```
Imported Summary:
- Vendors: 3
- Designs: 12
- Design Assets: 24
- Blank SKUs: 48
- Printed SKUs: 144
```

### Step 3: Verify Data in Django Admin

```bash
# Exit the shell (Ctrl+D)
exit()

# Start the dev server
python manage.py runserver
```

Navigate to: http://localhost:8000/admin/

Login with your superuser credentials. You should see:
- **Vendors**: 3 entries
- **Designs**: 12 entries
- **Blank SKUs**: 48 entries
- **Printed SKUs**: 144 entries

---

## Phase 3: Test All Workflows (20 minutes)

### Step 1: Test Admin Interface
- [ ] Go to http://localhost:8000/admin/
- [ ] Login
- [ ] View all models (Vendors, Designs, Blank SKUs, etc.)
- [ ] Edit a Blank SKU and change `on_hand` to 50, save
- [ ] Check that a StockMovement audit record was created

### Step 2: Test Print Batch View
- [ ] Go to http://localhost:8000/ops/print-batches/
- [ ] You should see "No pending orders" (because we haven't created orders yet)
- [ ] This page is working correctly

### Step 3: Test Forecast View
- [ ] Go to http://localhost:8000/ops/forecast/
- [ ] You should see all Printed SKUs listed with:
  - Available stock counts
  - Days of stock calculations
  - Risk highlighting (none yet since no sales)

### Step 4: Test Receive Dashboard
- [ ] Go to http://localhost:8000/ops/receive/
- [ ] You should see "No jobs in progress" (correct, no print jobs yet)

---

## Phase 4: Create Test Orders (15 minutes)

### Option A: Manual Django Shell (Recommended for testing)

```bash
python manage.py shell
```

Inside the shell:
```python
from core.models import Order, OrderLine, PrintedSKU, BlankSKU
from core.services.inventory import reserve_printed
import json

# Get a printed SKU to order
printed_sku = PrintedSKU.objects.first()

# Create a test order
order = Order.objects.create(
    shopify_order_id=f"test-order-{Order.objects.count() + 1}",
    order_no=f"ORD-{Order.objects.count() + 1:05d}",
    customer_name="Test Customer",
    email="test@example.com",
    tags=json.dumps(["test", "manual"]),
    status=Order.STATUS_NEW,
    fulfillment_status=Order.FULFILLMENT_UNFULFILLED,
    raw_payload={}
)

# Create order lines
line = OrderLine.objects.create(
    order=order,
    shopify_line_id=f"line-1",
    product_name=printed_sku.design.name,
    variant=printed_sku.variant or "BASE",
    size=printed_sku.size or "N/A",
    quantity=5,
    printed_sku=printed_sku,
    status=OrderLine.STATUS_TO_BE_PRINTED
)

# Reserve stock
reserve_printed(line)

print(f"Created order {order.order_no}")
print(f"Printed SKU: {printed_sku}")
print(f"Quantity: 5")
```

### Option B: Shopify Webhook (For production testing)

See DEPLOYMENT.md Part 4 for webhook testing with ngrok.

### Step 2: Verify Order in Admin

Go to http://localhost:8000/admin/core/order/

You should see your test order with:
- Order number
- Customer name
- Status: NEW
- 1 order line with NEEDS_PRINTING status

---

## Phase 5: Test Print Batch Workflow (10 minutes)

### Step 1: Visit Print Batch Suggestion
Go to http://localhost:8000/ops/print-batches/

You should see:
- A table row showing the test order's printed SKU
- Demand quantity: 5
- Buffer top-up recommendation (e.g., +25 to reach target of 30)
- Blank SKU information

### Step 2: Confirm a Batch

1. Select a vendor from the dropdown (you imported vendors)
2. Optional: Add notes (e.g., "Test batch")
3. Keep the suggested quantities (or edit them)
4. Click **"Confirm Batch"**

System should:
- ✅ Create a PrintBatch (status: DRAFT → CONFIRMED)
- ✅ Create a PrintJob
- ✅ Create PrintJobLines
- ✅ Deduct plain stock from BlankSKU
- ✅ Mark order as IN_PRINTING
- ✅ Display success message with print pack PDF link

### Step 3: Verify in Admin
Go to http://localhost:8000/admin/core/printjob/

You should see:
- 1 PrintJob
- Status: CONFIRMED
- Related PrintJobLines showing quantities

Go to http://localhost:8000/admin/core/order/

Your order should now show:
- Status: IN_PRINTING
- OrderLine status: IN_PRINTING

---

## Phase 6: Test Receive Workflow (10 minutes)

### Step 1: Visit Receive Dashboard
Go to http://localhost:8000/ops/receive/

You should see:
- Your PrintJob listed
- PrintJobLines showing quantities sent

### Step 2: Mark Line as Received

1. Click on the PrintJobLine
2. Enter:
   - Quantity received (good): 5
   - Quantity received (defective): 0
3. Click "Mark Received"

System should:
- ✅ Update PrintJobLine quantities
- ✅ Mark order as READY_TO_SHIP
- ✅ Create StockMovement audit record

### Step 3: Verify in Admin
Go to http://localhost:8000/admin/core/order/

Your order should now show:
- Status: READY_TO_SHIP
- All lines received

---

## Phase 7: Production Deployment (Docker)

### Step 1: Build Docker Image
```bash
docker build -t bolderp:latest .
```

### Step 2: Run with Docker Compose

Create `docker-compose.yml`:
```yaml
version: '3.9'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: bolderp
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  web:
    build: .
    command: /app/entrypoint.sh
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/bolderp
      DJANGO_SECRET_KEY: your-production-secret-key-here
      DEBUG: "False"
      ALLOWED_HOSTS: yourdomain.com
    depends_on:
      - db
    volumes:
      - ./media:/app/media

  worker:
    build: .
    command: python manage.py qcluster
    environment:
      DATABASE_URL: postgresql://postgres:postgres@db:5432/bolderp
      DJANGO_SECRET_KEY: your-production-secret-key-here
    depends_on:
      - db

volumes:
  postgres_data:
```

Start:
```bash
docker-compose up -d
```

Migrate in container:
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py shell < import_master_data.py
```

---

## Production Checklist

- [ ] **Database**: PostgreSQL running and accessible
- [ ] **Migrations**: All migrations applied
- [ ] **Master Data**: Vendors, designs, SKUs imported
- [ ] **Superuser**: Created for Django Admin
- [ ] **Static Files**: Collected (running `collectstatic`)
- [ ] **Environment Variables**: Set securely (DJANGO_SECRET_KEY, SHOPIFY_API_SECRET, etc.)
- [ ] **Debug Mode**: Set to False in production
- [ ] **ALLOWED_HOSTS**: Updated for your domain
- [ ] **SSL/HTTPS**: Configured on your web server
- [ ] **Backup**: Database backups automated
- [ ] **Logging**: Production logging configured
- [ ] **Monitoring**: Error tracking (Sentry) configured
- [ ] **Async Worker**: Django-Q2 cluster running

---

## Troubleshooting

### "No such table: core_blanksku"
Run migrations first: `python manage.py migrate`

### "Importer can't find Excel file"
Use full path: `run(r'C:\Users\...\Master_Data.xlsx')`

### Orders not showing in print batch view
Orders must have status `TO_BE_PRINTED` or `NEW` and not cancelled.

### Print batch confirm fails
Ensure blank SKU has sufficient on_hand inventory.

### Receive dashboard shows no jobs
Create orders first, then confirm a batch.

---

## Next Steps

1. **Configure Shopify**: Set up webhook URL (e.g., https://yourdomain.com/webhooks/shopify/)
2. **Set up Notifications**: Configure NTFY_TOPIC and RESEND for low-stock alerts
3. **Monitor Production**: Set up Sentry error tracking
4. **Backup Strategy**: Implement daily PostgreSQL backups
5. **Scale Workers**: Increase Q2_WORKERS as needed

