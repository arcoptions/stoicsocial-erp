# Test Data Scenarios for Testers

This directory contains pre-built test data scenarios that testers can upload to test different workflows and edge cases **without using the console**.

## How to Use

1. Go to **Inventory → Import Data** in BoldERP
2. Download the template CSV for the data type you want (Designs, Blank SKUs, Printed SKUs, or Orders)
3. Choose a scenario folder below and copy the CSV data into your template
4. Upload the filled template using the web form
5. Verify the data in the system

## Available Test Scenarios

### 1. `happy_path_basic/`
**Purpose:** Simple end-to-end workflow - create a design, link blank stock, create printed SKUs, and generate a print batch.

**Flow:**
- 1 design (Black color)
- 3 blank SKUs (S, M, L sizes)
- 3 printed SKUs (linked to the design)
- 2 orders with 1 line item each
- Expected result: Print batch suggestion works smoothly with full size grid

**When to use:** Initial smoke test, verify basic create/link/order flow

---

### 2. `multi_variant_design/`
**Purpose:** Test a single design with multiple variants (e.g., Raasi variants like Karkataka, Vruschika, Thula).

**Flow:**
- 1 design with 3 color variants
- 9 blank SKUs (3 colors × 3 sizes: S, M, L)
- 9 printed SKUs (one per color-size combo)
- 3 orders targeting different variants
- Expected result: Variant selector works, print batch differentiates by variant

**When to use:** Multi-variant product testing, variant differentiation in print batch

---

### 3. `missing_size_edge_case/`
**Purpose:** Test handling of orders missing size data - should trigger "Missing Size" warning in print batch UI.

**Flow:**
- 1 design
- 2 blank SKUs (only M and L, no S or XL)
- 2 printed SKUs
- 3 orders: 2 with valid sizes (M, L), 1 with **blank/empty size field**
- Expected result: Print batch UI shows red warning banner "Missing Size" before confirmation

**When to use:** Validate missing-size detection, UI warning display

---

### 4. `bulk_orders_stress/`
**Purpose:** Test system behavior with large order quantities and inventory shortfall scenarios.

**Flow:**
- 1 design
- 3 blank SKUs with **limited quantities** (10, 5, 3 units)
- 3 printed SKUs (low on_hand, high reorder targets)
- 5 orders with **large quantities** (50+ units each)
- Expected result: Inventory forecast shows shortage, print batch calculation handles bulk correctly

**When to use:** Capacity planning, inventory shortage detection, forecast validation

---

### 5. `multiple_designs_complex/`
**Purpose:** Test a realistic multi-design scenario with different colors and sizes per design.

**Flow:**
- 3 designs (Design A, Design B, Design C)
- 12 blank SKUs (varies by design)
- 24 printed SKUs (multiple colors and sizes)
- 8 orders across different designs
- Expected result: Print batch correctly groups by design and calculates all linked SKUs

**When to use:** Complex production day simulation, multi-design batch generation

---

### 6. `status_transition_testing/`
**Purpose:** Create orders at different statuses to test workflow state transitions.

**Flow:**
- 1 design
- 2 blank SKUs
- 2 printed SKUs
- 3 orders:
  - Order 1: `needs_printing` status
  - Order 2: `in_printing` status (line in `in_printing`)
  - Order 3: `ready_to_ship` status
- Expected result: UI correctly displays status labels, receive workflow only shows eligible orders

**When to use:** Validate status filtering, order state machine testing

---

## Quick Reference: Scenario Checklist

| Scenario | Designs | Orders | Focus | Upload Order |
|----------|---------|--------|-------|--------------|
| Happy Path | 1 | 2 | Basic workflow | designs → blank → printed → orders |
| Multi-Variant | 1 | 3 | Variant handling | designs → blanks → printed → orders |
| Missing Size | 1 | 3 | Size validation | designs → blanks → printed → orders |
| Bulk Orders | 1 | 5 | Inventory limits | designs → blanks → printed → orders |
| Multi-Design | 3 | 8 | Complex batch | designs → blanks → printed → orders |
| Status Transitions | 1 | 3 | Workflow states | designs → blanks → printed → orders |

## Important Rules

- **Always upload in this order:** Designs → Blank SKUs → Printed SKUs → Orders (dependencies must exist)
- **Sizes:** Use only `S, M, L, XL, XXL, XXXL` (no 2XL, 3XL, XS)
- **Quantities:** Use integers only
- **Colours:** Match across designs and blanks (e.g., if design is "Black", blank SKU must be "Black")
- **Leave blank:** Optional fields like variant, placement_note, tags
- **Naming:** Use clear names like "Design A", "Order #100" for easy identification

## Troubleshooting

**Error: "Design not found"**
- Upload designs CSV first before printed SKUs or orders

**Error: "Colour mismatch"**
- Ensure printed SKU colour matches the design's colour exactly (case-insensitive, but must match)

**Error: "Size not valid"**
- Use S, M, L, XL, XXL, XXXL only. No 2XL/3XL/XS

**Orders show "NA" size in print batch**
- The order CSV had a blank size field. Re-import with valid sizes.

---

## Next Steps: Production Data

Once testers complete their scenarios and validation:
1. Use the reset_and_seed_domain_data command to clear test data
2. Import production data using import_production_csv_bundle
3. See PRODUCTION_DATA_PLAYBOOK.md for deployment sequence
