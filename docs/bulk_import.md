# Bulk-importing products

Add many products at once from a spreadsheet instead of one by one.

```
database/products.csv  --->  scripts/import_products.py  --->  Django catalog or Flask products table
                                       |-- frontend/assets/images/<category>/   (pictures)
                                       '-- database/seed.sql                    (optional SQL copy)
```

The importer can target the standalone Flask `products` table (default) or the persistent Django
storefront catalog (`--django`). The desktop app in persistent mode reads the Django catalog.

## 1. Prepare your file

Accepted formats: **.csv .tsv .json .jsonl .xlsx** (Excel needs `pip install openpyxl`, already in requirements.txt).

| Column | Required | Notes |
|--------|----------|-------|
| `name` | yes | up to 150 characters |
| `category` | yes | e.g. `Electronics`, `Clothing`, `Footwear`, `Accessories` (a new name creates a new category) |
| `price` | yes | `19.99`, `$19.99`, `₹1,299.50` all work |
| `sku` | no | your stable product code, e.g. `ELE-0001`. Used to match existing products. If empty it is built from the category and name (`ELE-WIRELESS-MOUSE`), which stays the same on every run |
| `brand` | no | |
| `stock` | no | whole number, default 0 |
| `description` | no | |
| `image` | no | file name or path inside the images folder; leave empty to find it automatically (see Pictures) |
| `is_active` | no | `true/false`, `yes/no`, `1/0`. Inactive products are not shown. Default true |

Column names are flexible and case-insensitive: `Title` = name, `Department` = category, `Qty` = stock,
`Price (INR)` = price, `Photo` = image, and so on. Semicolon-separated files and Excel's UTF-8 BOM are fine.

Examples:

```csv
sku,name,category,brand,price,stock,description,image,is_active
CLO-0010,Linen Shirt,Clothing,NexusCart,24.99,40,"Breathable linen, relaxed fit",,true
FOO-0003,Canvas Sneakers,Footwear,,31.50,18,Lightweight everyday sneakers,,true
```

```json
[{"sku": "ACC-0010", "name": "Canvas Belt", "category": "Accessories", "price": 9.5, "stock": 60}]
```

(JSON can also be `{"products": [...]}`; `.jsonl` has one object per line.)

## 2. Check first, then import

```bash
python3 scripts/import_products.py database/products.csv --dry-run     # report only, changes nothing
python3 scripts/import_products.py database/products.csv               # import (adds new, updates existing)
python3 backend/manage.py migrate                                      # one-time setup for Django
python3 scripts/import_products.py database/products.csv --django      # import to Django storefront
```

The report shows how many rows were read, which rows have problems (by row number, same as in Excel,
where the header is row 1), how many pictures were found, and how many products were added or updated.

* Bad rows are **skipped** and saved to `import_errors.csv` with the problem next to your original columns.
  Fix that file and import it again.
* Use `--strict` to stop completely if any row has an error.
* Running the same file twice is safe: products are matched by SKU, so you get updates, not duplicates.
* The import is all-or-nothing for the database: if something fails halfway, nothing is saved.
* `--mode insert` only adds new products; `--mode update` only changes existing ones.

Which database? The one in `DATABASE_URL` (`.env`), or local SQLite if that is empty. Override with
`--database-url postgresql+psycopg2://user:pass@host/db`. For PostgreSQL run `database/schema.sql` first
(or, for an older database, `database/migrations/001_products_bulk_import.sql`).

With `--django`, the importer uses the Django database configured by `DATABASE_URL`, or
`backend/db.sqlite3` if it is unset. Run `python3 backend/manage.py migrate` first. Existing products
are matched by SKU, and importing a previously soft-deleted SKU restores that product.

## 3. Pictures

Pictures live in `frontend/assets/images/<category>/`, e.g. `electronics/`, `clothing/`, `footwear/`,
`accessories/` (new category folders are created automatically).

A product's picture is found by, in order: the `image` column, then `<sku>.png`, then `<name-slug>.png`
(`Wireless Mouse` -> `wireless-mouse.png`). `.png .jpg .jpeg .gif .webp` are accepted
(JPG/WEBP need `pip install pillow` for the desktop app). Products without a picture show a coloured tile.

* **You have a folder of pictures:** `--copy-images ~/Downloads/new_pictures` copies the matching ones into the
  right category folders (named by SKU if you gave one, otherwise by product name).
* **Pictures are loose in `images/`:** `--organize-images` moves them into their category folders.
* A picture link starting with `http` is stored as is (the desktop app does not download it yet).

## 4. Keep `seed.sql` in sync (optional)

```bash
python3 scripts/import_products.py database/products.csv --no-db --emit-sql database/seed.sql
```

This rewrites only the block between `-- BEGIN PRODUCTS` and `-- END PRODUCTS` in `seed.sql`
(your own SQL around it is kept), so a fresh Docker database starts with the same products.

## All options

| Option | What it does |
|--------|--------------|
| `--dry-run` | check everything, change nothing |
| `--strict` | stop if any row has an error |
| `--mode upsert\|insert\|update` | add + update (default), only add, or only update |
| `--sheet NAME` | Excel sheet (default: the first one) |
| `--images-dir DIR` | pictures folder (default `frontend/assets/images`) |
| `--copy-images DIR` | copy matching pictures from DIR |
| `--organize-images` | move loose pictures into category folders |
| `--emit-sql FILE` | also write the products as SQL |
| `--no-db` | do not touch the database |
| `--database-url URL` | use a different database |
| `--django` | import into Django's `store_product` catalog instead of Flask's `products` table |
| `--create-table` | in Flask mode, create the `products` table if missing (throw-away databases only) |
| `--errors-out FILE` | where rejected rows go (default `import_errors.csv`) |

Tip: add `import_errors.csv` to `.gitignore`.

## Troubleshooting

| Message | Fix |
|---------|-----|
| `Required column(s) missing: name, price` | the header row is not the first row, or columns are named differently; the message lists what it found |
| `'free' is not a valid price` | put a number in that cell |
| `duplicate SKU` | two rows share a code; make them unique |
| `The products table does not exist yet` | in Flask mode, run `database/schema.sql`; in Django mode, run `python3 backend/manage.py migrate` |
| `no picture for: ...` | not an error: add the pictures later and run the import again |
