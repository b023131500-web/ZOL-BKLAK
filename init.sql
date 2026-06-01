-- ZOL Price Bot — Schema
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- מוצרים
CREATE TABLE IF NOT EXISTS products (
    barcode         TEXT PRIMARY KEY,
    product_name    TEXT NOT NULL,
    manufacturer    TEXT,
    category        TEXT,
    image_url       TEXT,   -- מ-Open Food Facts
    unit_qty        TEXT,   -- כמות ביחידה (500g, 1L וכו')
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_name_trgm  ON products USING GIN (product_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_name_lower ON products (lower(product_name));
CREATE INDEX IF NOT EXISTS idx_products_category   ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_manufacturer ON products (manufacturer);

-- מחירי סניפים
CREATE TABLE IF NOT EXISTS branch_prices (
    id          BIGSERIAL PRIMARY KEY,
    barcode     TEXT NOT NULL REFERENCES products(barcode) ON DELETE CASCADE,
    chain_name  TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    branch_id   TEXT,
    city        TEXT,
    price       NUMERIC(10,2) NOT NULL,
    unit_price  NUMERIC(10,4),  -- מחיר ל-100g/100ml
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bp_barcode        ON branch_prices (barcode);
CREATE INDEX IF NOT EXISTS idx_bp_chain          ON branch_prices (chain_name);
CREATE INDEX IF NOT EXISTS idx_bp_price          ON branch_prices (price);
CREATE INDEX IF NOT EXISTS idx_bp_barcode_price  ON branch_prices (barcode, price);
CREATE INDEX IF NOT EXISTS idx_bp_city           ON branch_prices (city);

-- היסטוריית מחירים (לגרף ולמגמות)
CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    barcode     TEXT NOT NULL,
    chain_name  TEXT NOT NULL,
    price       NUMERIC(10,2) NOT NULL,
    recorded_at DATE NOT NULL DEFAULT CURRENT_DATE
);
CREATE INDEX IF NOT EXISTS idx_ph_barcode ON price_history (barcode, recorded_at DESC);

-- מנויי התראות (לאוטומציות)
CREATE TABLE IF NOT EXISTS price_alerts (
    id            BIGSERIAL PRIMARY KEY,
    barcode       TEXT NOT NULL,
    contact       TEXT NOT NULL,  -- מייל או מספר וואטסאפ
    contact_type  TEXT NOT NULL,  -- "email" | "whatsapp"
    target_price  NUMERIC(10,2),  -- שלח כשמחיר יורד מתחת לסכום זה
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_sent_at  TIMESTAMPTZ
);

-- View: המחיר הזול ביותר לכל מוצר
CREATE OR REPLACE VIEW cheapest_per_product AS
SELECT DISTINCT ON (bp.barcode)
    bp.barcode,
    p.product_name,
    p.manufacturer,
    p.category,
    p.image_url,
    bp.chain_name,
    bp.branch_name,
    bp.city,
    bp.price,
    bp.updated_at
FROM branch_prices bp
JOIN products p ON p.barcode = bp.barcode
ORDER BY bp.barcode, bp.price ASC;

-- View: השוואת מחירים לפי רשת
CREATE OR REPLACE VIEW chain_avg_prices AS
SELECT
    bp.barcode,
    p.product_name,
    bp.chain_name,
    ROUND(AVG(bp.price)::numeric, 2) AS avg_price,
    MIN(bp.price) AS min_price,
    COUNT(*) AS branch_count
FROM branch_prices bp
JOIN products p ON p.barcode = bp.barcode
GROUP BY bp.barcode, p.product_name, bp.chain_name;
