# models/owner.py -- Owner subclass of User; no extra fields yet.

from database.db import get_db_connection
from models.user import User


# A User with role='owner'. No additional fields yet.
class Owner(User):
    def __init__(self, user_id, email, password_hash, is_active, login_at=None):
        super().__init__(user_id, email, password_hash, role="owner",
                          is_active=is_active, login_at=login_at)

    # FR-E2: active owner accounts to notify on delivery -- there may be more than one (Bhargav + Ketki).
    @classmethod
    def list_active_emails(cls):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT email FROM users WHERE role = 'owner' AND is_active = 1"
            ).fetchall()
        finally:
            connection.close()
        return [row["email"] for row in rows]
