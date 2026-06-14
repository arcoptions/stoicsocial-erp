# Test Data Import Guide for Testers

## 📥 What is This?

A **web-based interface** (no console needed!) to upload test data into BoldERP for testing different scenarios without running Python commands.

### Access Point
**Navigate to:** Inventory → Import Data in the sidebar

**URL:** `/ops/inventory/import/`

---

## 🚀 Quick Start (3 Steps)

### Step 1: Download a CSV Template
Go to **Inventory → Import Data** and click one of these buttons:
- 🎨 **Download Designs Template** — For creating designs with colors and mockups
- 📦 **Download Blank SKUs Template** — For plain blank inventory
- 🖼️ **Download Printed SKUs Template** — For linking designs to blanks
- 📋 **Download Orders Template** — For creating test orders

### Step 2: Fill in Your Test Data
Open the downloaded CSV in Excel or Google Sheets and add your test data following the format shown. See **Format Requirements** below.

### Step 3: Upload and Import
- Select the data type from the dropdown
- Choose your filled CSV file
- Click **📤 Upload & Import**
- See the success message confirming how many rows were imported

---

## 📋 Format Requirements

| Requirement | Details |
|-------------|---------|
| **Sizes** | Only: S, M, L, XL, XXL, XXXL (NOT 2XL, 3XL, XS) |
| **Numbers** | Integers only (no decimals for quantities) |
| **Colours** | Must match across designs and blanks (case-insensitive) |
| **Optional fields** | Leave blank if not needed (variant, tags, placement_note, etc.) |
| **First row** | Must be header row with column names |
| **Encoding** | UTF-8 or UTF-8 with BOM |
| **Upload order** | **Always:** Designs → Blank SKUs → Printed SKUs → Orders |

---

## 📊 CSV Field Reference

### Designs CSV
```
design_name, product_type, sub_category, material, fit, colour, colour_hex, blank_fabric, artwork_url, mockup_url, print_areas, placement_note
```
- **design_name** (required): Name of your design
- **colour** (required): Must match blank SKU colors
- **colour_hex**: Hex color code (e.g., #1b1b1b for black)
- **artwork_url/mockup_url**: Links to image files
- Other fields: Can use defaults or leave blank

**Example row:**
```
My First Design, Tshirt, Regular, Cotton, Regular, Black, #1b1b1b, 180 GSM, https://example.com/art.png, https://example.com/mockup.png, Front, Center chest
```

### Blank SKUs CSV
```
fabric, colour, size, on_hand, reserved, reorder_min, reorder_target
```
- **fabric, colour, size** (required): Unique combination
- **on_hand** (required): Current inventory count
- **reserved**: Already allocated units
- **reorder_min/target**: For low-stock warnings

**Example rows:**
```
180 GSM, Black, S, 50, 0, 10, 30
180 GSM, Black, M, 50, 0, 10, 30
```

### Printed SKUs CSV
```
design_name, variant, colour, size, on_hand, reserved, buffer_min, buffer_target, buffer_max, blank_fabric
```
- **design_name** (required): Must exist in Designs table
- **colour, size** (required): Must match a blank SKU
- **blank_fabric**: Should match blank SKU fabric
- **variant**: Optional (leave blank if no variants)
- **buffer_min/target/max**: Reorder thresholds

**Example rows:**
```
My First Design, , Black, S, 10, 0, 3, 10, 20, 180 GSM
My First Design, , Black, M, 15, 0, 3, 10, 20, 180 GSM
```

### Orders CSV
```
shopify_order_id, order_no, customer_name, email, shopify_line_id, product_name, variant, colour, size, quantity, status, line_status, fulfillment_status, delivery_status, tags
```
- **shopify_order_id** (required): Unique order ID (can be TEST-001, HP-001, etc.)
- **product_name** (required): Must match a design name
- **colour, size** (required): Must match a printed SKU
- **quantity** (required): Integer
- **status**: Order status (needs_printing, in_printing, ready_to_ship, etc.)
- **line_status**: Item status within order (to_be_printed, in_printing, ready_to_ship)

**Valid Statuses:**
- Order: `needs_printing`, `in_printing`, `ready_to_ship`, `shipped`, `completed`
- Line: `to_be_printed`, `in_printing`, `ready_to_ship`

**Example rows:**
```
HP-001, #HP001, Alice Johnson, alice@example.com, HP-001-L1, My First Design, , Black, M, 2, needs_printing, to_be_printed, unfulfilled, pending, test,happy-path
HP-002, #HP002, Bob Smith, bob@example.com, HP-002-L1, My First Design, , Black, L, 1, needs_printing, to_be_printed, unfulfilled, pending, test,happy-path
```

---

## 🧪 Pre-Built Test Scenarios

Copy-paste ready CSV files are available in the codebase at:
```
docs/templates/test_scenarios/
```

### Available Scenarios

1. **happy_path_basic** — Simple 1-design workflow
2. **multi_variant_designs** — 1 design with 3 color variants
3. **missing_size_edge_case** — Tests missing-size warning detection
4. **bulk_orders_stress** — Large orders, low inventory (shortage testing)
5. **multi_design_complex** — 3 designs, 8 orders (realistic day)
6. **status_transition_testing** — Orders at different workflow states

**How to Use:**
1. Find the scenario folder (e.g., `happy_path_basic/`)
2. Copy the CSV data from each file in order:
   - `happy_path_basic_designs.csv`
   - `happy_path_basic_blank_skus.csv`
   - `happy_path_basic_printed_skus.csv`
   - `happy_path_basic_orders.csv`
3. Paste into your downloaded templates
4. Upload one at a time using the Import Data form

---

## ⚠️ Common Issues

### "Design not found" error
**Solution:** Upload designs CSV **first** before printed SKUs or orders.

### "Colour mismatch" error
**Solution:** Ensure printed SKU colour exactly matches design colour (case-insensitive but must be identical spelling).

### "Size not valid" error
**Solution:** Use only S, M, L, XL, XXL, XXXL. Avoid 2XL/3XL/XS.

### Orders show "NA" size in Print Batch
**Solution:** Your CSV had a blank size field. Re-import with valid sizes in every row.

### Import seems to do nothing
**Solution:** Check browser console (F12) for error messages. Ensure:
- CSV file is valid (no hidden characters)
- No duplicate header rows
- All required columns present

---

## 🔄 Workflow Examples

### Example 1: Test Basic Print Batch Flow
1. Upload `happy_path_basic_designs.csv` (1 design)
2. Upload `happy_path_basic_blank_skus.csv` (stock)
3. Upload `happy_path_basic_printed_skus.csv` (printed inventory)
4. Upload `happy_path_basic_orders.csv` (2 orders)
5. Go to **Inventory → Print Batches** and verify:
   - Both orders appear
   - Size grid shows S, M, L
   - No missing-size warnings

### Example 2: Test Missing Size Detection
1. Upload `missing_size_designs.csv`
2. Upload `missing_size_blank_skus.csv`
3. Upload `missing_size_printed_skus.csv`
4. Upload `missing_size_orders.csv` (has 1 order with blank size)
5. Go to **Inventory → Print Batches** and verify:
   - Red warning banner appears: "Missing Size"
   - Shows which rows have NA size

### Example 3: Test Multi-Design Batch
1. Upload all CSVs from `multi_design_*` folder
2. Go to **Inventory → Print Batches** and verify:
   - Batch suggestion groups by design
   - All 3 designs appear in batch list
   - Size coverage correct for each design

---

## 🛠️ Advanced: Custom Test Data

To create your own test scenario:
1. Download all 4 templates
2. Create a scenario directory: `docs/templates/test_scenarios/my_scenario/`
3. Save your filled CSVs with naming: `my_scenario_designs.csv`, etc.
4. Share with team or document in scenario README

---

## 📚 Data Integrity Notes

- **Duplicates:** Importing the same row twice will update, not duplicate
- **Partial deletes:** Import doesn't delete existing data; use Django Admin bulk actions to delete
- **Atomic uploads:** Each import is transactional; fails completely or succeeds completely (no partial imports)
- **Test flag:** All imported data is marked `is_test_data=True` for easy cleanup later

---

## ✅ Checklist Before Testing

- [ ] Downloaded CSV template for your data type
- [ ] Filled in all required columns
- [ ] Used correct size values (S, M, L, XL, XXL, XXXL)
- [ ] Verified colours match across designs and blanks
- [ ] Planning upload order: Designs → Blanks → Printed → Orders
- [ ] No hidden characters or extra spaces in CSV
- [ ] File encoding is UTF-8

---

## 🚀 Next Steps After Import

Once data is imported:
1. **View Orders:** Inventory → Orders
2. **Generate Print Batch:** Inventory → Print Batches
3. **View Print Pack PDF:** Click "View" on batch
4. **Test Receive:** Inventory → Receive
5. **Check Audit Log:** Inventory → Audit Log (see all changes)

---

## 📞 Support

For errors or issues:
1. Check the **⚠️ Common Issues** section above
2. Verify CSV format matches templates
3. Check browser console (F12 → Console tab) for detailed error messages
4. Contact development team with error screenshot

---

**That's it!** You can now test BoldERP workflows without touching the console. 🎉
