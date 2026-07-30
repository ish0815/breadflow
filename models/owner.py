# models/owner.py -- Owner subclass of User; no extra fields yet.

from models.user import User


# A User with role='owner'. No additional fields yet.
class Owner(User):
    def __init__(self, user_id, email, password_hash, is_active, login_at=None):
        super().__init__(user_id, email, password_hash, role="owner",
                          is_active=is_active, login_at=login_at)
