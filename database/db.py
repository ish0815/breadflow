# database/db.py -- thin SQLite connection helper. No ORM, per the SRS's tech constraints.

import sqlite3
from pathlib import Path

# gitignored -- real client data never hits version control (NF-06)
DATABASE_PATH = Path(__file__).resolve().parent.parent / "instance" / "breadflow.db"

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# Row access by column name + FK enforcement on. Caller closes the connection.
def get_db_connection():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Runs schema.sql. Safe on every startup -- all CREATE TABLEs use IF NOT EXISTS.
def init_db():
    connection = get_db_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        connection.executescript(schema_file.read())
    connection.close()
