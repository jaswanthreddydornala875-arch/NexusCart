-- Run once on a database created from the OLD schema.sql (fresh databases already have these columns).
-- PostgreSQL.  psql "$DATABASE_URL" -f database/migrations/001_products_bulk_import.sql

ALTER TABLE products ADD COLUMN IF NOT EXISTS sku        VARCHAR(40);
ALTER TABLE products ADD COLUMN IF NOT EXISTS brand      VARCHAR(80);
ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active  BOOLEAN     NOT NULL DEFAULT TRUE;
ALTER TABLE products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- give existing rows a SKU so the column can become NOT NULL + UNIQUE
UPDATE products SET sku = 'LEGACY-' || id WHERE sku IS NULL;
ALTER TABLE products ALTER COLUMN sku SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products (sku);
