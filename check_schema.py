import sqlite3
conn = sqlite3.connect('instance/breadflow.db')
rows = conn.execute("SELECT sql FROM sqlite_master WHERE name IN ('orders','deliveries')").fetchall()
for row in rows:
    print(row[0])
    print("---")
