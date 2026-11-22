PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    business_key TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK (source = 'books'),
    source_id INTEGER NOT NULL UNIQUE CHECK (source_id > 0),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
    category TEXT NOT NULL CHECK (length(category) > 0),
    currency TEXT NOT NULL CHECK (currency = 'GBP'),
    price_pence INTEGER NOT NULL CHECK (price_pence > 0),
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    in_stock INTEGER CHECK (in_stock IN (0, 1)),
    product_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    parser_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    business_key TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK (source = 'fx'),
    currency TEXT NOT NULL CHECK (currency = 'GBP'),
    rate_date TEXT NOT NULL CHECK (date(rate_date) IS rate_date),
    nominal INTEGER NOT NULL CHECK (nominal = 1),
    rub_x10000 INTEGER NOT NULL CHECK (rub_x10000 > 0),
    quote_field TEXT NOT NULL CHECK (quote_field IN ('Value', 'Previous')),
    source_url TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    UNIQUE (currency, rate_date)
);

CREATE TABLE IF NOT EXISTS product_history (
    business_key TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    change_kind TEXT NOT NULL CHECK (change_kind IN ('insert', 'update')),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    price_pence INTEGER NOT NULL,
    rating INTEGER,
    in_stock INTEGER,
    PRIMARY KEY (business_key, updated_at)
);

CREATE TRIGGER IF NOT EXISTS product_insert_history AFTER INSERT ON products
BEGIN
    INSERT INTO product_history VALUES (
        NEW.business_key, NEW.updated_at, 'insert', NEW.title, NEW.category,
        NEW.price_pence, NEW.rating, NEW.in_stock
    );
END;

CREATE TRIGGER IF NOT EXISTS product_update_history AFTER UPDATE ON products
BEGIN
    INSERT INTO product_history VALUES (
        NEW.business_key, NEW.updated_at, 'update', NEW.title, NEW.category,
        NEW.price_pence, NEW.rating, NEW.in_stock
    );
END;

CREATE INDEX IF NOT EXISTS idx_products_currency_category ON products(currency, category);

CREATE VIEW IF NOT EXISTS priced_catalogue AS
SELECT p.business_key, p.source_id, p.title, p.category, p.currency,
       p.price_pence, p.rating, p.in_stock, p.product_url, p.collected_at,
       r.rate_date, r.rub_x10000,
       (p.price_pence * r.rub_x10000 + 5000) / 10000 AS price_rub_kopeks
FROM products p
JOIN exchange_rates r ON p.currency = r.currency;
