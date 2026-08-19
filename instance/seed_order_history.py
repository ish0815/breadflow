import sqlite3
import random
from datetime import datetime, timedelta

conn = sqlite3.connect('instance/breadflow.db')
cur = conn.cursor()

WEEKDAY = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
    'Friday': 4, 'Saturday': 5, 'Sunday': 6,
}

OWNER_USER_ID = 1  # owner@test.com
OVERDUE_CLIENT_NAMES = ['Honest', 'Sandwich House']

REJECTION_REASONS = [
    "Product currently unavailable due to a supply shortage.",
    "Requested quantity exceeds the agreed pack size for this product.",
    "Order submitted after the 4pm daily cut-off.",
    "Delivery date clashes with a public holiday production schedule.",
]

SPECIAL_INSTRUCTIONS = [
    None, None, None,
    "Leave at back door.",
    "Please call on arrival.",
    "Side entrance access only after 3pm.",
]

# real driver ids, pulled live so we don't hardcode a guess
cur.execute("SELECT user_id FROM users WHERE role = 'driver'")
driver_ids = [row[0] for row in cur.fetchall()]
if not driver_ids:
    print("WARNING: no driver accounts found. Delivered orders will use driver_id = NULL-safe fallback of owner id.")
    driver_ids = [OWNER_USER_ID]

# real clients (excluding Test Cafe) with their catalogue
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

# week offsets: negative = past, positive = future. Spread across both financial years.
DELIVERED_OFFSETS = [-30, -24, -18, -12, -6]   # ~7 months of history, crosses 1 Jul FY boundary
REJECTED_OFFSET = -2
APPROVED_OFFSET = 1
PENDING_OFFSET = 2

orders_created = {'delivered': 0, 'approved': 0, 'rejected': 0, 'pending': 0}

for client_id, business_name, day1, day2 in clients:
    cur.execute("""
        SELECT product_id, agreed_price, pack_size FROM client_products
        WHERE client_id = ?
    """, (client_id,))
    catalogue = cur.fetchall()

    def make_order(weeks_offset, status, with_delivery=False, rejection_reason=None):
        day_name = day1 if weeks_offset % 2 == 0 else day2
        base_date = today + timedelta(weeks=weeks_offset)
        delivery_date = next_weekday_on_or_after(base_date, day_name)
        created_at = delivery_date - timedelta(days=random.randint(2, 5))

        approved_by = OWNER_USER_ID if status in ('approved', 'delivered') else None
        approved_at = (created_at + timedelta(hours=random.randint(1, 20))).strftime('%Y-%m-%dT%H:%M:%S') if approved_by else None

        cur.execute("""
            INSERT INTO orders (client_id, delivery_date, order_status, special_instructions,
                                 order_created_at, approved_by, approved_at, rejection_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            client_id,
            delivery_date.strftime('%Y-%m-%d'),
            status,
            random.choice(SPECIAL_INSTRUCTIONS),
            created_at.strftime('%Y-%m-%dT%H:%M:%S'),
            approved_by,
            approved_at,
            rejection_reason,
        ))
        order_id = cur.lastrowid

        num_items = random.randint(1, min(3, len(catalogue)))
        chosen = random.sample(catalogue, num_items)
        for product_id, agreed_price, pack_size in chosen:
            qty = pack_size * random.randint(1, 3)
            cur.execute("""
                INSERT INTO order_lines (order_id, product_id, quantity, unit_price)
                VALUES (?, ?, ?, ?)
            """, (order_id, product_id, qty, agreed_price))

        if with_delivery:
            delivered_at = delivery_date.replace(hour=random.randint(9, 15), minute=random.choice([0, 15, 30, 45]))
            cur.execute("""
                INSERT INTO deliveries (order_id, driver_id, delivery_date, delivery_status, delivered_at)
                VALUES (?, ?, ?, 'delivered', ?)
            """, (
                order_id,
                random.choice(driver_ids),
                delivery_date.strftime('%Y-%m-%d'),
                delivered_at.strftime('%Y-%m-%dT%H:%M:%S'),
            ))

        return order_id

    # overdue-demo clients skip their most recent delivered offset too, not just
    # the future approved/pending ones below -- otherwise their last order sits
    # exactly one interval out, which never trips FR-F3's 1.5x-avg-interval rule
    delivered_offsets = (DELIVERED_OFFSETS[:-1] if business_name in OVERDUE_CLIENT_NAMES
                          else DELIVERED_OFFSETS)
    for offset in delivered_offsets:
        make_order(offset, 'delivered', with_delivery=True)
        orders_created['delivered'] += 1

    make_order(REJECTED_OFFSET, 'rejected', rejection_reason=random.choice(REJECTION_REASONS))
    orders_created['rejected'] += 1

    if business_name not in OVERDUE_CLIENT_NAMES:
        make_order(APPROVED_OFFSET, 'approved')
        orders_created['approved'] += 1

        make_order(PENDING_OFFSET, 'pending')
        orders_created['pending'] += 1
    else:
        print(f"Skipping upcoming orders for {business_name} — left overdue for FR-F3 demo")

    print(f"Seeded orders for {business_name}")

conn.commit()
conn.close()

print()
print("Done. Orders created by status:", orders_created)
print("Total new orders:", sum(orders_created.values()))