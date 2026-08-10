# test_driver_routing.py -- Criterion 8 test evidence: FR-A3 role routing for the
# driver portal (login redirect, /driver/dashboard 403 for wrong roles).
# Permanent test script -- keep in the repo, do not delete.

from app import app

app.config["TESTING"] = True
client = app.test_client()

# real account IDs from the committed DB (see users table)
OWNER_ID, CLIENT_ID, DRIVER_ID = 1, 3, 13


def seed_session(user_id, role):
    with client.session_transaction() as sess:
        sess.clear()
        sess["user_id"] = user_id
        sess["role"] = role


# 1. driver session -> GET /login (the "already logged in" branch) should redirect
#    to /driver/dashboard via DASHBOARD_ENDPOINT["driver"] = "driver.dashboard"
seed_session(DRIVER_ID, "driver")
response = client.get("/login")
assert response.status_code == 302, f"expected 302, got {response.status_code}"
assert response.headers["Location"] == "/driver/dashboard", response.headers["Location"]
print("PASS: driver session redirects /login -> /driver/dashboard")

followed = client.get("/driver/dashboard")
assert followed.status_code == 200, followed.status_code
assert b"Today's deliveries will appear here" in followed.data
assert b"Driver dashboard" in followed.data
print("PASS: /driver/dashboard renders driver_dashboard.html shell (200)")

# 2. owner/client sessions must be blocked from /driver/dashboard with 403
seed_session(OWNER_ID, "owner")
response = client.get("/driver/dashboard")
assert response.status_code == 403, f"owner expected 403, got {response.status_code}"
print("PASS: owner session gets 403 on /driver/dashboard")

seed_session(CLIENT_ID, "client")
response = client.get("/driver/dashboard")
assert response.status_code == 403, f"client expected 403, got {response.status_code}"
print("PASS: client session gets 403 on /driver/dashboard")

# 3. owner/client dashboards still work unchanged
seed_session(OWNER_ID, "owner")
response = client.get("/owner/dashboard")
assert response.status_code == 200, response.status_code
print("PASS: /owner/dashboard still 200")

seed_session(CLIENT_ID, "client")
response = client.get("/client/dashboard")
assert response.status_code == 200, response.status_code
print("PASS: /client/dashboard still 200")

print("\nAll checks passed.")
