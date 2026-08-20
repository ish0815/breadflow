# models/driver.py -- Driver subclass of User; no separate driver table (Module E).

from database.db import get_db_connection
from models.user import User


# A User with role='driver'. No additional fields yet.
class Driver(User):
    def __init__(self, user_id, email, password_hash, is_active, login_at=None):
        super().__init__(user_id, email, password_hash, role="driver",
                          is_active=is_active, login_at=login_at)

    # Bread Staple runs a single driver today -- deterministically picks the
    # earliest active driver account so approval always assigns the same one.
    # Revisit with a real picker if/when a second driver is added.
    @classmethod
    def get_default(cls):
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT user_id FROM users WHERE role = 'driver' AND is_active = 1 "
                "ORDER BY user_id LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        return row["user_id"] if row else None
