# BoldERP New Data Templates

Fill these CSV files in this order. Keep the header row unchanged and save as UTF-8 CSV.

## 1. vendors.csv

One row per print vendor.

- `name`: Required unique vendor name.
- `contact`: Email, phone, or operating contact details.
- `is_active`: `true` or `false`.

## 2. designs.csv

One row per design and garment colour.

- `design_name`: Required; must match Shopify product title exactly.
- `product_type`: Use `Tshirt`.
- `sub_category`: Use `Regular`.
- `material`: Garment material, normally `Cotton`.
- `fit`: `Regular` or `Oversized`.
- `colour`: Required; use one consistent spelling across every CSV.
- `colour_hex`: Hex colour such as `#1b1b1b`.
- `blank_fabric`: Must match `fabric` in `blank_skus.csv`.
- `artwork_url`: Publicly reachable production artwork URL.
- `mockup_url`: Publicly reachable product mockup URL.
- `print_areas`: Example: `Front`, `Back`, or `Front, Back`.
- `placement_note`: Vendor placement instructions.
- `notes`: Optional internal notes.

## 3. blank_skus.csv

One row per fabric, colour, and size combination.

- `fabric`, `colour`, `size`, `on_hand`: Required.
- `reserved`: Start at `0` for a clean deployment.
- `reorder_min`: Low-stock alert threshold.
- `reorder_target`: Desired stock after replenishment.

## 4. printed_skus.csv

One row per design, variant, colour, and size combination sold on Shopify.

- `design_name`, `colour`, `size`: Required.
- `variant`: Leave blank for products with no non-size variant.
- `on_hand`: Opening finished/printed stock.
- `reserved`: Start at `0` for a clean deployment.
- `buffer_min`, `buffer_target`, `buffer_max`: Finished-stock buffer settings.
- `blank_fabric`: Must match a blank SKU with the same colour and size.

## Orders

Do not add orders to this bundle. New orders are created only from Shopify's registered inbound webhooks after master inventory data has been imported.

The production webhook endpoint is:

```text
https://erp.boldanditalic.in/webhooks/shopify/
```

Shopify must keep the `orders/create`, `orders/updated`, `orders/cancelled`, and `orders/fulfilled` subscriptions active.

## Valid Values

- Sizes: `XS`, `S`, `M`, `L`, `XL`, `XXL`, `XXXL`, `4XL`.
- Quantities and money values must be integers.

## Validation

Run before importing:

```bash
python manage.py import_production_csv_bundle --dir docs/templates/data_input --dry-run
```
