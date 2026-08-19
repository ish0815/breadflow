import sqlite3
import random
from datetime import datetime, timedelta

conn = sqlite3.connect('instance/breadflow.db')
cur = conn.cursor()

WEEKDAY = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6,
}
OWNER_USER_ID = 1

cur.execute("SELECT user_id FROM users WHERE role = 'driver'")
driver_ids = [row[0] for row in cur.fetchall()] or [OWNER_USER_ID]
OVERDUE_CLIENT_NAMES = ['Honest', 'Sandwich House']

cur.execute("""
    SELECT client_id, business_name, delivery_day1, delivery_day2
    FROM clients WHERE business_name != 'Test Cafe'
""")
clients = cur.fetchall()

def next_weekday_on_or_after(start_date, weekday_name):
    target = WEEKDAY[weekday_name]
    days_ahead = (target - start_date.weekday()) % 7
    return start_date + timedelta(days=days_ahead)

today = datetime.now()
created = 0

for client_id, business_name, day1, day2 in clients:
    cur.execute("SELECT product_id, agreed_price, pack_size FROM client_products WHERE client_id = ?", (client_id,))
    catalogue = cur.fetchall()
    if business_name in OVERDUE_CLIENT_NAMES:
        print(f"Skipping recent delivery for {business_name} — left overdue for FR-F3 demo")
        continue
    # land squarely inside the last ~10 days
    base_date = today - timedelta(days=random.randint(3, 9))
    delivery_date = next_weekday_on_or_after(base_date, day1)
    if delivery_date > today:
        delivery_date = next_weekday_on_or_after(base_date, day2)
    if delivery_date > today:
        delivery_date = today - timedelta(days=1)

    created_at = delivery_date - timedelta(days=random.randint(2, 4))
    approved_at = (created_at + timedelta(hours=random.randint(1, 12))).strftime('%Y-%m-%dT%H:%M:%S')

    cur.execute("""
        INSERT INTO orders (client_id, delivery_date, order_status, order_created_at, approved_by, approved_at)
        VALUES (?, ?, 'delivered', ?, ?, ?)
    """, (client_id, delivery_date.strftime('%Y-%m-%d'), created_at.strftime('%Y-%m-%dT%H:%M:%S'), OWNER_USER_ID, approved_at))
    order_id = cur.lastrowid

    num_items = random.randint(1, min(3, len(catalogue)))
    for product_id, agreed_price, pack_size in random.sample(catalogue, num_items):
        qty = pack_size * random.randint(1, 3)
        cur.execute("INSERT INTO order_lines (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                     (order_id, product_id, qty, agreed_price))

    delivered_at = delivery_date.replace(hour=random.randint(9, 15), minute=random.choice([0, 15, 30, 45]))
    cur.execute("""
        INSERT INTO deliveries (order_id, driver_id, delivery_date, delivery_status, delivered_at)
        VALUES (?, ?, ?, 'delivered', ?)
    """, (order_id, random.choice(driver_ids), delivery_date.strftime('%Y-%m-%d'), delivered_at.strftime('%Y-%m-%dT%H:%M:%S')))

    created += 1
    print(f"Recent delivered order added for {business_name} on {delivery_date.strftime('%Y-%m-%d')}")

conn.commit()
conn.close()
print(f"\nDone. {created} recent delivered orders added.")