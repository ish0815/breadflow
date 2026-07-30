# models/driver.py -- Driver subclass of User; no separate driver table (Module 5).

from models.user import User


# A User with role='driver'. No additional fields yet.
class Driver(User):
    def __init__(self, user_id, email, password_hash, is_active, login_at=None):
        super().__init__(user_id, email, password_hash, role="driver",
                          is_active=is_active, login_at=login_at)
