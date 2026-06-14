# BoldERP Schema Refactor: Simplified Linking Model

## What Changed?

### Before: Redundant Per-Size Linking
```
Design "Aata Choostava"
├── Colour "Black"
│   ├── Size S → blank_sku_id (redundant)
│   ├── Size M → blank_sku_id (same, stored 6 times)
│   ├── Size L → blank_sku_id
│   ├── Size XL → blank_sku_id
│   ├── Size 2XL → blank_sku_id
│   └── Size 3XL → blank_sku_id
```

**Problem:** Same blank SKU stored 6 times, no mockup file tracking.

### After: Smart One-Link-Per-Color
```
Design "Aata Choostava"
└── Colour "Black"
    ├── blank_sku → "Unisex T-Shirt / Black / All Sizes" ✅ (one link)
    └── Mockup Files
        ├── Front Preview (mockup)
        ├── Back Preview (mockup)
        ├── Front Print File (print_file)
        └── Back Print File (print_file)
        
All sizes (S, M, L, XL, 2XL, 3XL) automatically use the same blank SKU ✅
```

---

## Key Benefits

✅ **No Redundancy** - One blank SKU link per design+colour (not per-size)
✅ **Mockup Tracking** - Track front, back, sleeve, full print files
✅ **Auto Population** - All sizes auto-inherit blank SKU from design_asset
✅ **Test Data Management** - Import/delete test orders easily
✅ **Better Admin UI** - DesignAsset admin shows files inline

---

## New Admin Interface

### 1. Manage Mockup Files

**Path:** Django Admin → Designs → Select Design → Colours → View Files

**Example:**
```
Design: "Aata Choostava"
  └─ Colour: "Black"
      ├─ Blank SKU: "Unisex T-Shirt / Black" [link one time]
      └─ Files:
          ├─ Type: Mockup | Placement: Front | URL: https://...
          ├─ Type: Mockup | Placement: Back  | URL: https://...
          ├─ Type: Print File | Placement: Full | URL: https://...
```

### 2. Simplified Linking

**Old Way (Per-Size, Redundant):**
```
PrintedSKU: Aata Choostava / Black / S
├─ blank_sku: Unisex T-Shirt / Black / S
PrintedSKU: Aata Choostava / Black / M
├─ blank_sku: Unisex T-Shirt / Black / M  [repeat 6 times]
...
```

**New Way (Per-Color, Smart):**
```
DesignAsset: Aata Choostava / Black
└─ blank_sku: Unisex T-Shirt / Black [ONE link for all sizes]

All PrintedSKU for this design+colour auto-populate from here ✅
```

### 3. Test Data Management

**Commands:**

```bash
# 1. Export template
python manage.py export_test_template --output my_tests.csv

# 2. Fill in CSV with test scenarios
# order_id, customer_name, email, design_name, colour, size, quantity
# TEST-0001, John Doe, john@test.com, Aata Choostava, Black, L, 2

# 3. Import test orders
python manage.py import_test_orders my_tests.csv

# 4. Verify (Django Admin → Orders)
# Filter by: is_test_data = True

# 5. Delete after testing
python manage.py delete_test_data --no-confirm
```

---

## How to Use the New UI

### Scenario 1: Link a Design to a Blank SKU

**Steps:**
1. Go to Django Admin → **Designs**
2. Click on design name "Aata Choostava"
3. Scroll to **Colours** section
4. Click on "Black" colour row
5. Set **Blank SKU** → "Unisex T-Shirt / Black"
6. Save
7. ✅ All 6 sizes (S, M, L, XL, 2XL, 3XL) now use this blank SKU

**Code Equivalent:**
```python
design_asset = DesignAsset.objects.get(design__name="Aata Choostava", colour="Black")
design_asset.blank_sku = BlankSKU.objects.get(fabric="Unisex T-Shirt", colour="Black")
design_asset.save()
```

### Scenario 2: Upload Mockup Files

**Steps:**
1. Go to Django Admin → **Design Assets**
2. Click on "Aata Choostava / Black"
3. Scroll to **Files** section (bottom)
4. Click "Add File"
5. Fill in:
   - **File Type:** Mockup / Print File
   - **Placement:** Front / Back / Sleeve / Full
   - **File URL:** https://cdn.example.com/mockup_front.jpg
6. Save
7. ✅ Mockup now accessible for print batch generation

**Access in Code:**
```python
design_asset = DesignAsset.objects.get(...)
mockup_files = design_asset.files.filter(file_type='mockup')
for file in mockup_files:
    print(f"{file.placement}: {file.file_url}")
```

### Scenario 3: Test Different Order Scenarios

**Create Test CSV:**
```csv
order_id,customer_name,email,design_name,colour,size,quantity
TEST-0001,John Doe,john@test.com,Aata Choostava,Black,L,2
TEST-0002,Jane Smith,jane@test.com,Aata Choostava,Black,M,1
TEST-0003,Bob Johnson,bob@test.com,Different Design,White,XL,3
```

**Import & Test:**
```bash
python manage.py import_test_orders test_scenarios.csv
python manage.py test tests/test_order_flow.py
```

**Cleanup:**
```bash
python manage.py delete_test_data
```

---

## Migration Reference

### Database Changes

**New Table:** `DesignAssetFile`
```sql
CREATE TABLE core_designassetfile (
  id UUID PRIMARY KEY,
  design_asset_id UUID (FK → DesignAsset),
  file_type VARCHAR(30),  -- mockup, print_file, artwork
  placement VARCHAR(30),  -- front, back, sleeve, full
  file_url VARCHAR(600),
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

**New Fields:**

| Table | Field | Type | Purpose |
|-------|-------|------|---------|
| DesignAsset | blank_sku_id | FK | Link to BlankSKU |
| PrintedSKU | design_asset_id | FK | Reference to colour variant |
| PrintedSKU | is_test_data | Boolean | Mark test orders |
| Order | is_test_data | Boolean | Mark test orders |

### Backward Compatibility

During migration, **both** `PrintedSKU.blank_sku` and `PrintedSKU.design_asset` are populated:

```python
printed_sku = PrintedSKU.objects.first()
print(printed_sku.blank_sku)  # Still works ✓
print(printed_sku.design_asset.blank_sku)  # Preferred ✓
```

Automatically sync on save:
```python
printed_sku.design_asset = DesignAsset.objects.get(...)
printed_sku.save()  # blank_sku auto-populated from design_asset
```

---

## Troubleshooting

### "Multiple blank SKUs for same design+colour"

**Issue:** Some sizes of "Aata Choostava / Black" use different blank SKUs.

**Fix:**
```bash
# Identify conflict
python manage.py populate_design_asset_blanks --dry-run

# Choose the most common one, set at design_asset level
# Then manually align outliers
```

### "Mockup file not showing in print batch"

**Check:**
1. File exists in DesignAsset → Files
2. File type is "mockup" (not "print_file")
3. File URL is accessible

**Debug:**
```python
from core.models import DesignAsset
asset = DesignAsset.objects.get(design__name="...", colour="...")
print(asset.files.all())
print(asset.files.filter(file_type='mockup'))
```

### "Test data not deleting"

**Ensure:**
```bash
# Check is_test_data flag is set
python manage.py shell
>>> from core.models import Order
>>> Order.objects.filter(is_test_data=True).count()

# If 0, mark before deleting
>>> Order.objects.filter(shopify_order_id__startswith="TEST-").update(is_test_data=True)
```

---

## Support

For questions or issues:
1. Check [SCHEMA_MIGRATION_GUIDE.md](./SCHEMA_MIGRATION_GUIDE.md) for migration steps
2. Run `python manage.py check_schema_consistency` to validate
3. Check Django Admin → Order/PrintedSKU for data integrity

---

## Next Steps

- [ ] Test in staging environment
- [ ] Import sample test orders
- [ ] Verify print batch generation
- [ ] Deploy to production (follow SCHEMA_MIGRATION_GUIDE.md)
- [ ] Monitor order sync logs
