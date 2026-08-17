# database/db.py -- thin SQLite connection helper. No ORM, per the SRS's tech constraints.

import sqlite3
from pathlib import Path

# intentionally committed (not gitignored) -- keeps dev/demo data consistent across
# machines; a deliberate project convention, not an NF-06 compliance gap
DATABASE_PATH = Path(__file__).resolve().parent.parent / "instance" / "breadflow.db"

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# Row access by column name + FK enforcement on. Caller closes the connection.
def get_db_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Adds products.gst_applicable to a pre-existing DB (SQLite has no ADD COLUMN IF
# NOT EXISTS). Safe every startup -- checks table_info first, no-ops if present.
def _migrate_products_gst_applicable(connection):
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
    if "gst_applicable" in columns:
        return
    connection.execute(
        "ALTER TABLE products ADD COLUMN gst_applicable INTEGER NOT NULL DEFAULT 0 "
        "CHECK (gst_applicable IN (0, 1))"
    )
    connection.commit()


# Adds orders.rejection_reason to a pre-existing DB (FR-B4). Same safe-every-startup
# pattern as _migrate_products_gst_applicable.
def _migrate_orders_rejection_reason(connection):
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)")}
    if "rejection_reason" in columns:
        return
    connection.execute(
        "ALTER TABLE orders ADD COLUMN rejection_reason TEXT "
        "CHECK (rejection_reason IS NULL OR LENGTH(rejection_reason) <= 300)"
    )
    connection.commit()


# Runs schema.sql. Safe on every startup -- all CREATE TABLEs use IF NOT EXISTS.
def init_db():
    connection = get_db_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        connection.executescript(schema_file.read())
    _migrate_products_gst_applicable(connection)
    _migrate_orders_rejection_reason(connection)
    connection.close()
