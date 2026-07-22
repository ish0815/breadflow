-- database/schema.sql
-- BreadFlow database schema. Built incrementally as each module is developed;
-- currently covers Module 1 (Login) only: `users` + `clients`.
--
-- Design decision: clients get their OWN table with its own primary key
-- (client_id), rather than folding business fields onto `users`, because
-- every other module in the design docs (Orders, Invoices, ClientCatalogue,
-- Analytics) references "clientID" as a foreign key in its own right --
-- e.g. orders.clientID, invoices.clientID, client_products.clientID.
-- Treating client data as columns on `users` would mean every one of those
-- FKs actually points to users.user_id, contradicting the data dictionaries
-- for Modules 2-12.
--
-- Drivers do NOT get a separate table yet: Module 5's data dictionary
-- defines `driverID` as "FK to users table", so a driver's identity is
-- fully described by a row in `users` with role = 'driver'. A `drivers`
-- table will only be added if a later module (vehicle info, fixed route
-- assignment, etc.) turns out to need driver-specific columns.

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,      -- FR-A1: login lookup key
    password_hash TEXT NOT NULL,             -- bcrypt hash only (NF-06) -- never plaintext
    role          TEXT NOT NULL CHECK (role IN ('owner', 'client', 'driver')),  -- FR-A3
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),       -- SQLite has no native BOOLEAN
    created_at    TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')),
    -- FR-A1 data dictionary: "Timestamp of successful login ... Set server-side
    -- ... Cannot be in the future". NULL until the account's first successful
    -- login (e.g. a client created by Module 11 who hasn't logged in yet).
    -- No CHECK constraint needed for "cannot be in the future": this column
    -- is only ever written by User.authenticate() using the database's own
    -- STRFTIME('now'), never from user-supplied input, so a future value is
    -- not reachable through the application.
    login_at      TEXT
);

CREATE TABLE IF NOT EXISTS clients (
    client_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    business_name   TEXT NOT NULL UNIQUE,    -- Module 7: trading name, default A-Z sort key
    -- Exactly 11 digits, no separators: GLOB with 11 single-digit character
    -- classes enforces both the length AND that every character is 0-9 in
    -- one constraint, so a value like "123 456 789" or a 10-digit ABN is
    -- rejected at the database layer, not just in Python.
    abn             TEXT NOT NULL UNIQUE
                    CHECK (abn GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'),
    delivery_zone   TEXT NOT NULL CHECK (delivery_zone IN ('Western', 'Northern', 'Eastern', 'Southern')),
    delivery_day1   TEXT NOT NULL,           -- FR-B1: first of 2 fixed weekly delivery days
    delivery_day2   TEXT NOT NULL CHECK (delivery_day2 != delivery_day1),
    delivery_charge REAL NOT NULL CHECK (delivery_charge > 0),
    internal_notes  TEXT                     -- Module 11: owner-only, must never reach the client portal
);
