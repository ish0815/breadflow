-- database/schema.sql -- BreadFlow schema, built incrementally per module.
-- clients has its own table/PK since other modules FK to clientID directly.
-- No drivers table yet -- role='driver' on users covers it for now.

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,      -- FR-A1: login lookup key
    password_hash TEXT NOT NULL,             -- bcrypt hash only (NF-06) -- never plaintext
    role          TEXT NOT NULL CHECK (role IN ('owner', 'client', 'driver')),  -- FR-A3
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),       -- SQLite has no native BOOLEAN
    created_at    TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')),
    -- null until first login; only ever written server-side via STRFTIME('now')
    login_at      TEXT
);

CREATE TABLE IF NOT EXISTS clients (
    client_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    business_name   TEXT NOT NULL UNIQUE,    -- Module A: trading name, default A-Z sort key
    -- GLOB enforces exactly 11 digits, no separators
    abn             TEXT NOT NULL UNIQUE
                    CHECK (abn GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    delivery_zone   TEXT NOT NULL CHECK (delivery_zone IN ('Western', 'Northern', 'Eastern', 'Southern')),
    delivery_day1   TEXT NOT NULL,           -- FR-B1: first of 2 fixed weekly delivery days
    delivery_day2   TEXT NOT NULL CHECK (delivery_day2 != delivery_day1),
    delivery_charge REAL NOT NULL CHECK (delivery_charge > 0),
    internal_notes  TEXT                     -- Module A: owner-only, must never reach the client portal
);

-- Module B: master product record. Per-client price/pack size live on client_products.
CREATE TABLE IF NOT EXISTS products (
    product_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name   TEXT NOT NULL UNIQUE,
    category       TEXT NOT NULL CHECK (category IN ('Bread', 'Pastry', 'Savoury')),
    base_price     REAL NOT NULL CHECK (base_price > 0),
    pack_size      INTEGER NOT NULL CHECK (pack_size > 0),
    -- Section 7.2: most bakery goods are ATO GST-exempt food; flag defaults free,
    -- owner can override per product if a future non-exempt item is added
    gst_applicable INTEGER NOT NULL DEFAULT 0 CHECK (gst_applicable IN (0, 1))
);

-- ClientCatalogue (FR-B2): gates what a client can see/order -- no row here, no access.
CREATE TABLE IF NOT EXISTS client_products (
    catalogue_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id          INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    product_id         INTEGER NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    agreed_price       REAL NOT NULL CHECK (agreed_price > 0),  -- per-client negotiated price; overrides products.base_price
    pack_size          INTEGER NOT NULL CHECK (pack_size > 0),  -- per-client agreed pack size; overrides products.pack_size
    UNIQUE (client_id, product_id)
);

-- FR-B1/B3/B4. No delivery_charge/gst/total columns -- computed on read
-- (GST/delivery only apply at invoicing, FR-D1), so nothing here can drift.
CREATE TABLE IF NOT EXISTS orders (
    order_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id            INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    -- validated against the client's 2 assigned weekdays in Order.place()
    delivery_date        TEXT NOT NULL,
    order_status         TEXT NOT NULL DEFAULT 'pending'
                         CHECK (order_status IN ('pending', 'approved', 'rejected', 'delivered')),
    special_instructions TEXT CHECK (special_instructions IS NULL OR LENGTH(special_instructions) <= 300),
    order_created_at     TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')),
    approved_by          INTEGER REFERENCES users(user_id),  -- NULL while pending (FR-B4)
    approved_at          TEXT,
    -- set only when order_status = 'rejected' (FR-B4)
    rejection_reason     TEXT CHECK (rejection_reason IS NULL OR LENGTH(rejection_reason) <= 300)
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    -- locked in from client_products.agreed_price at order time
    unit_price    REAL NOT NULL CHECK (unit_price > 0)
);

-- FR-C1/FR-C2: audit log of generation events, not read back to build the list
CREATE TABLE IF NOT EXISTS production_lists (
    production_list_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    production_date     TEXT NOT NULL,
    generated_by        INTEGER NOT NULL REFERENCES users(user_id),
    generated_at         TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')),
    approved_order_count INTEGER NOT NULL CHECK (approved_order_count >= 0),
    total_client_count   INTEGER NOT NULL CHECK (total_client_count >= 0)
);

-- one row per product per list; no clientID -- bakers see product totals only
CREATE TABLE IF NOT EXISTS production_lines (
    production_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_list_id INTEGER NOT NULL REFERENCES production_lists(production_list_id) ON DELETE CASCADE,
    product_id          INTEGER NOT NULL REFERENCES products(product_id),
    total_ordered       INTEGER NOT NULL CHECK (total_ordered >= 0),
    buffer_qty          INTEGER NOT NULL CHECK (buffer_qty >= 0),
    produce_qty         INTEGER NOT NULL CHECK (produce_qty >= 0)
);

-- FR-D1 Module D: one invoice per client per generated billing period, batch-generated
-- across every client with approved orders in range ("Generate All Invoices").
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id             INTEGER NOT NULL REFERENCES clients(client_id),
    billing_period_start  TEXT NOT NULL,
    billing_period_end    TEXT NOT NULL CHECK (billing_period_end >= billing_period_start),
    -- GST-free/taxable split is flag-driven per product line (products.gst_applicable),
    -- not a blanket "products are always GST-free" rule
    gst_free_subtotal     REAL NOT NULL CHECK (gst_free_subtotal >= 0),
    -- taxable product lines + delivery_charge_total (delivery is always taxable)
    taxable_subtotal      REAL NOT NULL CHECK (taxable_subtotal >= 0),
    -- clients.delivery_charge x approved_order_count -- a flat PER-ORDER fee, and a
    -- billing period typically spans several of the client's 2 fixed weekly deliveries
    delivery_charge_total REAL NOT NULL CHECK (delivery_charge_total >= 0),
    approved_order_count  INTEGER NOT NULL CHECK (approved_order_count >= 0),
    gst_amount            REAL NOT NULL CHECK (gst_amount >= 0),  -- 10% of taxable_subtotal
    invoice_total         REAL NOT NULL CHECK (invoice_total >= 0),
    invoice_status        TEXT NOT NULL DEFAULT 'draft' CHECK (invoice_status IN ('draft', 'sent', 'paid')),
    pdf_path              TEXT,  -- set once export_to_pdf() writes the file
    generated_by          INTEGER NOT NULL REFERENCES users(user_id),
    generated_at          TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')),
    sent_at               TEXT  -- null until owner sends/emails (draft -> sent)
);

-- One row per (product, unit_price) aggregated across the client's approved orders
-- in the period -- grouped by price too, not just product, so a mid-period agreed_price
-- change can't silently blend two different prices into one wrong-total line (NF03).
CREATE TABLE IF NOT EXISTS invoice_lines (
    invoice_line_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      REAL NOT NULL CHECK (unit_price > 0),
    -- snapshot of products.gst_applicable at generation time -- a later flag change
    -- must never retroactively alter an already-generated invoice
    gst_applicable  INTEGER NOT NULL CHECK (gst_applicable IN (0, 1))
);

-- FR-E1/FR-E2 Module E: one delivery per approved order, assigned to a driver by the
-- owner. UNIQUE(order_id) -- an order is delivered at most once.
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id               INTEGER NOT NULL UNIQUE REFERENCES orders(order_id) ON DELETE CASCADE,
    driver_id              INTEGER NOT NULL REFERENCES users(user_id),
    delivery_date          TEXT NOT NULL,
    delivery_status        TEXT NOT NULL DEFAULT 'pending' CHECK (delivery_status IN ('pending', 'delivered')),
    proof_photo_path       TEXT,
    delivered_at           TEXT,
    -- snapshot of orders.special_instructions at creation -- read-only on driver screen (FR-E1)
    special_instructions   TEXT CHECK (special_instructions IS NULL OR LENGTH(special_instructions) <= 300)
);
