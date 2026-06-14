# Production Data Playbook

This playbook standardizes how BoldERP data is reset, seeded, and imported to avoid inconsistent records.

## 1. Objectives

- Keep sizes explicit (no blank or NA rows in production imports).
- Keep design/colour assets linked to plain fabric consistently.
- Keep printed SKUs linked to valid design assets and blank SKUs.
- Make imports repeatable and auditable.

## 2. Files You Should Edit

Use these templates under `docs/templates/data_input/`:

- `designs.csv`
- `blank_skus.csv`
- `printed_skus.csv`
- `orders.csv`

## 3. Full Reset + Sample Baseline (One Command)

This command deletes all operational/finance data and seeds a known-good sample baseline:

```bash
python manage.py reset_and_seed_domain_data --yes
```

Optional (generate sample print pack too):

```bash
python manage.py reset_and_seed_domain_data --yes --build-print-pack
```

What it does:

- Deletes inventory, order, print, webhook, and finance rows.
- Seeds canonical blank SKUs (`180 GSM`, `Black/White`, `S..XXXL`).
- Seeds designs/assets/mockups with valid size-based printed SKUs.
- Seeds sample orders and a sample print job.
- Generates a print pack URL for immediate validation.

## 4. Production-Ready CSV Import

After filling templates, run:

```bash
python manage.py import_production_csv_bundle --dir docs/templates/data_input
```

Dry-run validation only:

```bash
python manage.py import_production_csv_bundle --dir docs/templates/data_input --dry-run
```

## 5. Data Rules (Mandatory)

- `size` must be one of: `XS`, `S`, `M`, `L`, `XL`, `XXL`, `XXXL`, `4XL`.
- Never use `Unknown` colour in production templates.
- `printed_skus.csv` rows must have matching `design_name + colour` in `designs.csv`.
- `blank_fabric` in `printed_skus.csv` must map to an existing row in `blank_skus.csv` for each size.
- `orders.csv` lines should match an existing printed SKU using product + variant + colour + size.

## 6. Deployment Runbook

1. Backup current DB.
2. Pull latest code.
3. Run migrations.
4. Run CSV dry-run.
5. Run real CSV import.
6. Run consistency checks.
7. Generate one print pack and visually verify size grid + mockup.

Recommended command sequence:

```bash
python manage.py migrate --noinput
python manage.py import_production_csv_bundle --dir docs/templates/data_input --dry-run
python manage.py import_production_csv_bundle --dir docs/templates/data_input
python manage.py check_schema_consistency
```

## 7. Railway Commands

```bash
railway run python manage.py migrate --noinput
railway run python manage.py import_production_csv_bundle --dir docs/templates/data_input --dry-run
railway run python manage.py import_production_csv_bundle --dir docs/templates/data_input
```

For a clean re-initialization:

```bash
railway run python manage.py reset_and_seed_domain_data --yes
```

## 8. Quick Validation Checklist

- No print-pack pages show `NA` size unless intentionally seeded.
- Mockups render for all design/colour assets used in print jobs.
- Suggested print batch shows no missing-size warning rows.
- No order lines are created with empty size from manual CSV input.
