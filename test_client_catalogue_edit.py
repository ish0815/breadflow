# test_client_catalogue_edit.py -- Criterion 8 test evidence: Module 12 catalogue edit
# route (routes/owner.py edit_client_products, models/client.py
# Client.update_product_catalogue()) -- toggling products on/off and editing agreed
# price updates only the targeted client, never another client or products.base_price.
# Permanent test script -- keep in the repo, do not delete.

from app import app
from database.db import get_db_connection

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


def _make_test_client(connection, business_name, abn):
    user_cursor = connection.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?, 'x', 'client')",
        (f"{abn}@catalogue-edit-test.local",),
    )
    user_id = user_cursor.lastrowid
    client_cursor = connection.execute(
        """
        INSERT INTO clients (user_id, business_name, abn, delivery_zone,
            delivery_day1, delivery_day2, delivery_charge)
        VALUES (?, ?, ?, 'Western', 'Monday', 'Thursday', 15.0)
        """,
        (user_id, business_name, abn),
    )
    client_id = client_cursor.lastrowid
    connection.commit()
    return client_id, user_id


def _add_catalogue_entry(connection, client_id, product_id, agreed_price, pack_size):
    connection.execute(
        "INSERT INTO client_products (client_id, product_id, agreed_price, pack_size) VALUES (?, ?, ?, ?)",
        (client_id, product_id, agreed_price, pack_size),
    )
    connection.commit()


def _catalogue_rows(connection, client_id):
    rows = connection.execute(
        "SELECT product_id, agreed_price, pack_size FROM client_products "
        "WHERE client_id = ? ORDER BY product_id",
        (client_id,),
    ).fetchall()
    return {row["product_id"]: (row["agreed_price"], row["pack_size"]) for row in rows}


client_ids = []

try:
    connection = get_db_connection()
    try:
        product_rows = connection.execute(
            "SELECT product_id, base_price, pack_size FROM products ORDER BY product_id LIMIT 3"
        ).fetchall()
        product_1, product_2, product_3 = (dict(row) for row in product_rows)
        original_base_prices = {p["product_id"]: p["base_price"] for p in (product_1, product_2, product_3)}

        client_a_id, user_a_id = _make_test_client(connection, "Catalogue Test Client A", "93000000001")
        client_b_id, user_b_id = _make_test_client(connection, "Catalogue Test Client B", "93000000002")
        client_ids.append((client_a_id, user_a_id))
        client_ids.append((client_b_id, user_b_id))

        # A starts with products 1 & 2; B starts with products 1 & 3, at different prices
        _add_catalogue_entry(connection, client_a_id, product_1["product_id"], 5.00, 10)
        _add_catalogue_entry(connection, client_a_id, product_2["product_id"], 8.00, 5)
        _add_catalogue_entry(connection, client_b_id, product_1["product_id"], 6.00, 12)
        _add_catalogue_entry(connection, client_b_id, product_3["product_id"], 3.00, 20)
    finally:
        connection.close()

    seed_session(OWNER_ID, "owner")

    # GET pre-fills from the client's current catalogue
    response = client.get(f"/owner/clients/{client_a_id}/products")
    assert response.status_code == 200, response.status_code
    assert b'value="5.0"' in response.data or b'value="5"' in response.data, response.data
    print("PASS: edit form pre-fills the client's current agreed prices")

    # Edit client A only: drop product 2, reprice product 1, add product 3 --
    # product 2's checkbox and every other real product are simply omitted (unchecked)
    response = client.post(
        f"/owner/clients/{client_a_id}/products",
        data={
            f"product_{product_1['product_id']}": "on",
            f"price_{product_1['product_id']}": "7.50",
            f"product_{product_3['product_id']}": "on",
            f"price_{product_3['product_id']}": "4.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200, response.status_code
    assert b"Catalogue updated successfully." in response.data
    print("PASS: catalogue edit succeeds with a success flash")

    connection = get_db_connection()
    try:
        catalogue_a = _catalogue_rows(connection, client_a_id)
        catalogue_b = _catalogue_rows(connection, client_b_id)
        base_prices_after = {
            row["product_id"]: row["base_price"]
            for row in connection.execute(
                "SELECT product_id, base_price FROM products WHERE product_id IN (?, ?, ?)",
                (product_1["product_id"], product_2["product_id"], product_3["product_id"]),
            ).fetchall()
        }
    finally:
        connection.close()

    # client A: product 2 gone, product 1 repriced (pack size carried over from before),
    # product 3 newly added at the base product's default pack size
    assert set(catalogue_a.keys()) == {product_1["product_id"], product_3["product_id"]}, catalogue_a
    assert catalogue_a[product_1["product_id"]] == (7.50, 10), catalogue_a[product_1["product_id"]]
    assert catalogue_a[product_3["product_id"]] == (4.00, product_3["pack_size"]), catalogue_a[product_3["product_id"]]
    print("PASS: client A's catalogue reflects the toggle-off, reprice, and add-new")

    # client B untouched by client A's edit
    assert catalogue_b == {
        product_1["product_id"]: (6.00, 12),
        product_3["product_id"]: (3.00, 20),
    }, catalogue_b
    print("PASS: client B's catalogue is completely unaffected by client A's edit")

    # products.base_price is never written to by this feature
    assert base_prices_after == original_base_prices, (base_prices_after, original_base_prices)
    print("PASS: products.base_price is unchanged")

    print("\nAll checks passed.")
finally:
    cleanup_connection = get_db_connection()
    try:
        for client_id, user_id in client_ids:
            cleanup_connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        cleanup_connection.commit()
    finally:
        cleanup_connection.close()
    print(f"cleanup: removed {len(client_ids)} test client(s) (client_products cascade with them)")
