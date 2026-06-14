# Schema Refactor Migration Guide

## Overview

This guide explains the database schema changes for optimizing the Printed Stock linking model. The refactor moves blank SKU linking from PrintedSKU (per-size level) to DesignAsset (per-colour level), reducing duplication and improving data integrity.

**Key Changes:**
- ✅ Blank SKU linked at **design + colour** level (DesignAsset), not per-size
- ✅ New DesignAssetFile table for tracking mockup files (front, back, sleeve, etc.)
- ✅ PrintedSKU now references DesignAsset directly
- ✅ Test data tracking (is_test_data flag) for easy cleanup

---

## Database Schema Changes

### Before
```
Design
└── PrintedSKU (per size)
    ├── design_id
    ├── colour
    ├── size
    └── blank_sku_id ← Per-size linking (redundant)
```

### After
```
Design
├── DesignAsset (per colour)
│   ├── design_id
│   ├── colour
│   ├── blank_sku_id ← ONE link for all sizes ✅
│   └── DesignAssetFile[]
│       ├── file_type (mockup, print_file, artwork)
│       ├── placement (front, back, sleeve, full)
│       └── file_url
└── PrintedSKU (per size)
    ├── design_asset_id ← Reference to colour variant
    ├── size
    ├── is_test_data ← For cleanup
```

---

## Migration Steps

### Phase 1: Development / Testing (This Branch)

1. **Apply migrations**
   ```bash
   python manage.py migrate
   ```

2. **Verify schema changes**
   ```bash
   python manage.py dbshell
   # Check: DesignAsset.blank_sku, DesignAssetFile table, PrintedSKU.design_asset, is_test_data
   ```

3. **Test data import/export (optional)**
   ```bash
   # Export template
   python manage.py export_test_template --output test_orders.csv
   
   # Import test orders
   python manage.py import_test_orders test_orders.csv
   
   # Delete test data after testing
   python manage.py delete_test_data
   ```

### Phase 2: Staging / Pre-Production

1. **Backup production database**
   ```bash
   # PostgreSQL
   pg_dump boldmap > backup_$(date +%Y%m%d_%H%M%S).sql
   ```

2. **Run migrations on staging**
   ```bash
   python manage.py migrate --noinput
   ```

3. **Populate DesignAsset.blank_sku from existing PrintedSKU links**
   ```bash
   python manage.py populate_design_asset_blanks
   ```

4. **Test workflows**
   - Create print batches (should auto-populate blank SKU from design_asset)
   - Link mockup files
   - Import/export test orders

### Phase 3: Production Rollout

1. **Maintenance window: Stop all order syncs**
   ```bash
   # Disable Shopify webhook handlers temporarily
   # Set DISABLE_WEBHOOKS=true in environment
   ```

2. **Backup production database**
   ```bash
   pg_dump boldmap > backup_production_$(date +%Y%m%d_%H%M%S).sql
   ```

3. **Run migrations**
   ```bash
   python manage.py migrate --noinput
   ```

4. **Populate DesignAsset.blank_sku (production)**
   ```bash
   python manage.py populate_design_asset_blanks --production
   ```

5. **Verify data integrity**
   ```bash
   python manage.py check_schema_consistency
   ```

6. **Re-enable webhooks**
   ```bash
   # Set DISABLE_WEBHOOKS=false
   ```

7. **Monitor**
   - Check for errors in logs
   - Verify print batches create correctly
   - Check order line resolution

---

## Backward Compatibility

**During Migration:**
- PrintedSKU.blank_sku remains populated for backward compatibility
- PrintedSKU.design_asset can be NULL initially
- Auto-sync from DesignAsset when saving PrintedSKU

**Old Code:**
```python
# Still works (backward compatible)
printed_sku.blank_sku  # Returns from design_asset.blank_sku if not explicitly set
```

**New Code (Preferred):**
```python
# Use design_asset for linking
printed_sku.design_asset.blank_sku

# Or access directly
printed_sku.design_asset.files.filter(file_type='mockup')
```

---

## New Features: Test Data Management

### Import Test Orders
```bash
# Create template
python manage.py export_test_template --output test_orders.csv

# Fill in CSV with test scenarios
# Columns: order_id, customer_name, email, design_name, colour, size, quantity

# Import
python manage.py import_test_orders test_orders.csv

# Verify
python manage.py shell
>>> from core.models import Order
>>> Order.objects.filter(is_test_data=True).count()
```

### Delete Test Data
```bash
# View what will be deleted
python manage.py delete_test_data  # Shows summary

# Confirm deletion
python manage.py delete_test_data --no-confirm  # Skip prompt
```

### Test Scenarios Supported
- ✅ Full stock (all sizes available)
- ✅ Partial stock (some sizes out of stock)
- ✅ Backorder (zero stock, can still order)
- ✅ Multi-variant orders (different colours)
- ✅ Bulk orders (large quantities)
- ✅ Cancellations (mark as cancelled status)

---

## Data Validation

### Check Schema Consistency
```bash
python manage.py check_schema_consistency
```

This validates:
- All PrintedSKU have a design_asset or blank_sku reference
- DesignAsset.blank_sku matches expected BlankSKU for fabric/colour
- No orphaned DesignAssetFiles
- All inventory items are either test_data=True or False (no NULLs)

### Rollback Plan

If issues arise:
```bash
# Option 1: Restore from backup
psql boldmap < backup_production_YYYYMMDD_HHMMSS.sql

# Option 2: Revert migration
python manage.py migrate core 0006_printedsku_blank_sku
```

---

## Testing Checklist

- [ ] Migrations apply without errors
- [ ] Schema consistency checks pass
- [ ] Test orders import successfully
- [ ] Print batch creation works (blank_sku auto-populated)
- [ ] Mockup file linking works
- [ ] Test data deletion works
- [ ] No performance regression on order sync
- [ ] No errors in order line resolution

---

## Performance Considerations

**Indexes Added:**
- `PrintedSKU.design_asset_id` - Faster design asset lookups
- `DesignAssetFile.design_asset_id` - Faster file lookups

**Reduced Queries:**
- Single DesignAsset lookup instead of design + colour pair
- Mockup files directly available via design_asset.files

---

## Questions & Support

If migrations fail:
1. Check database constraints (unique key violations)
2. Verify BlankSKU references are valid
3. Review error logs for specific issues

Contact: Infrastructure Team
