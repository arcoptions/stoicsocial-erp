# 📊 Test Data Import Quick Reference

## 🚀 3-Minute Setup

1. **Go to:** Inventory → Import Data
2. **Click:** Download template for your data
3. **Fill:** CSV with test data (copy examples from `docs/templates/test_scenarios/`)
4. **Upload:** Using the form

## ✅ Valid Values

### Sizes
✅ S, M, L, XL, XXL, XXXL
❌ 2XL, 3XL, XS, Small, Medium, Large

### Order Status
- `needs_printing` (default)
- `in_printing`
- `ready_to_ship`
- `shipped`
- `completed`

### Line Item Status
- `to_be_printed` (default)
- `in_printing`
- `ready_to_ship`

## 📝 CSV Column Requirements

### Designs
| Column | Required | Example |
|--------|----------|---------|
| design_name | ✅ | My First Design |
| colour | ✅ | Black |
| colour_hex | ❌ | #1b1b1b |
| blank_fabric | ❌ | 180 GSM |
| artwork_url | ❌ | https://... |
| mockup_url | ❌ | https://... |

### Blank SKUs
| Column | Required | Example |
|--------|----------|---------|
| fabric | ✅ | 180 GSM |
| colour | ✅ | Black |
| size | ✅ | M |
| on_hand | ✅ | 50 |

### Printed SKUs
| Column | Required | Example |
|--------|----------|---------|
| design_name | ✅ | My First Design |
| colour | ✅ | Black |
| size | ✅ | M |
| blank_fabric | ✅ | 180 GSM |
| on_hand | ✅ | 15 |

### Orders
| Column | Required | Example |
|--------|----------|---------|
| shopify_order_id | ✅ | TEST-001 |
| product_name | ✅ | My First Design |
| colour | ✅ | Black |
| size | ✅ | M |
| quantity | ✅ | 2 |
| status | ✅ | needs_printing |

## 🎯 Upload Order (IMPORTANT!)
```
1️⃣ Designs
     ↓
2️⃣ Blank SKUs
     ↓
3️⃣ Printed SKUs
     ↓
4️⃣ Orders
```

## 🧪 Pre-Built Scenarios
All ready to copy-paste from `docs/templates/test_scenarios/`:

| Scenario | Purpose | Orders |
|----------|---------|--------|
| happy_path_basic | Basic workflow | 2 |
| multi_variant_designs | Multiple colors | 3 |
| missing_size_edge_case | Size validation | 3 |
| bulk_orders_stress | Large quantities | 5 |
| multi_design_complex | 3 designs | 8 |
| status_transition_testing | Different statuses | 3 |

## 🚨 Errors & Fixes

| Error | Fix |
|-------|-----|
| "Design not found" | Upload designs CSV first |
| "Colour mismatch" | Ensure design colour = blank SKU colour |
| "Size not valid" | Use S, M, L, XL, XXL, XXXL only |
| "CSV is empty" | File has no rows (only header?) |
| Nothing happens | Check browser console (F12) for errors |

## 💡 Tips
- Leave optional columns blank (don't delete them)
- Numbers are integers (50, not 50.0)
- Colours are case-insensitive but must match exactly
- Duplicate rows = update, not insert again
- All imported data marked as test data for easy cleanup

---
**Detailed guide:** See `TESTER_IMPORT_GUIDE.md`
