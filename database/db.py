"""
database/db.py -- thin SQLite connection helper.

Why a plain sqlite3 connection instead of an ORM (e.g. SQLAlchemy):
the SRS's own technical constraints (Section 4.1 / 7.4) chose SQLite
specifically for its simplicity and lack of a separate server process at
Bread Staple's scale (~160 orders/week). Layering an ORM on top would
reintroduce exactly the abstraction and setup complexity SQLite was chosen
to avoid, so every model queries the database directly with parameterised
SQL strings instead.
"""

import sqlite3
from pathlib import Path

# instance/ is gitignored (see .gitignore), so the actual database file --
# which will hold real client business data (ABNs, emails) once populated --
# is never committed to version control (NF-06, Privacy Act 1988 s.APP 11).
DATABASE_PATH = Path(__file__).resolve().parent.parent / "instance" / "breadflow.db"

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_db_connection():
    """
    Opens and returns a new SQLite connection configured for BreadFlow's needs:

    - row_factory = sqlite3.Row so query results are accessed by column name
      (row["email"]) instead of by fragile positional index -- this matters
      because every model below reads several columns per row and a
      reordered SELECT * would silently break positional access.
    - "PRAGMA foreign_keys = ON" because SQLite disables foreign-key
      enforcement by default; without this, deleting a user could silently
      leave an orphaned row in `clients` instead of raising an error.

    Caller is responsible for closing the returned connection.
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    """
    Creates every table defined in schema.sql if it does not already exist.

    Safe to call on every application startup: every CREATE TABLE in
    schema.sql uses "IF NOT EXISTS", so re-running this against a database
    that already has data never drops or recreates anything.
    """
    connection = get_db_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        connection.executescript(schema_file.read())
    connection.close()
