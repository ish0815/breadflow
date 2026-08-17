# test_client_welcome_email.py -- Criterion 8 test evidence: FR-A2 welcome email sent
# when the owner creates a new client account (routes/owner.py add_client()).
# Permanent test script -- keep in the repo, do not delete.

from app import app
from database.db import get_db_connection
from email_utils import mail

app.config["TESTING"] = True
client = app.test_client()

OWNER_ID = 1  # real owner account id from the committed DB (see users table)

BUSINESS_NAME = "Welcome Test Cafe"
EMAIL = "welcome-test@example.local"
ABN = "99999999901"
TEMP_PASSWORD = "TempPass123"


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


# connection closes in finally -- a failed statement must not leave a lock-holding connection open
def _first_product_id():
    connection = get_db_connection()
    try:
        return connection.execute("SELECT product_id FROM products LIMIT 1").fetchone()["product_id"]
    finally:
        connection.close()


created_user_id = None  # set once add_client succeeds, used for cleanup below

try:
    product_id = _first_product_id()
    seed_session(OWNER_ID, "owner")

    # 1. FR-A2: creating a client sends exactly one welcome email with the login details
    with mail.record_messages() as outbox:
        response = client.post(
            "/owner/clients/new",
            data={
                "business_name": BUSINESS_NAME,
                "abn": ABN,
                "email": EMAIL,
                "temp_password": TEMP_PASSWORD,
                "delivery_zone": "Western",
                "delivery_day1": "Monday",
                "delivery_day2": "Thursday",
                "delivery_charge": "15.00",
                f"product_{product_id}": "on",
                f"price_{product_id}": "5.00",
                f"pack_{product_id}": "10",
            },
            follow_redirects=True,
        )
    assert response.status_code == 200, response.status_code
    assert f"{BUSINESS_NAME} added.".encode() in response.data
    print("PASS: creating a client succeeds and redirects with a success flash")

    connection = get_db_connection()
    try:
        user_row = connection.execute("SELECT user_id FROM users WHERE email = ?", (EMAIL,)).fetchone()
    finally:
        connection.close()
    assert user_row is not None, "expected the new client's user row to exist"
    created_user_id = user_row["user_id"]
    print("PASS: new client's user/client rows were created")

    # TESTING=True (set above) makes Flask-Mail suppress real SMTP sends automatically --
    # record_messages() still captures them via blinker signals, so no network call happens here.
    assert len(outbox) == 1, outbox
    welcome_message = outbox[0]
    assert welcome_message.recipients == [EMAIL], welcome_message.recipients
    assert TEMP_PASSWORD in welcome_message.body, welcome_message.body
    assert EMAIL in welcome_message.body, welcome_message.body
    print("PASS: welcome email sent to the new client with their login email and temp password")

    print("\nAll checks passed.")
finally:
    if created_user_id is not None:
        cleanup_connection = get_db_connection()
        try:
            # ON DELETE CASCADE removes the clients row (and client_products with it)
            cleanup_connection.execute("DELETE FROM users WHERE user_id = ?", (created_user_id,))
            cleanup_connection.commit()
        finally:
            cleanup_connection.close()
        print(f"cleanup: removed test client user_id={created_user_id}")
