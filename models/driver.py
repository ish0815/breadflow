"""
models/driver.py -- Driver subclass of User.

Module 5's data dictionary defines `driverID` as "FK to users table" for
the Delivery class, meaning a driver's identity is already fully described
by a `users` row with role='driver' -- the design docs have no separate
driver-profile table. This class exists so drivers participate in the same
User -> subclass hierarchy as Owner and Client, and so delivery-assignment
methods (added when Module 5 is built) have a role-appropriate place to live.
"""

from models.user import User


class Driver(User):
    """A Driver is a User with role='driver' and no additional fields (yet)."""

    def __init__(self, user_id, email, password_hash, is_active):
        """Construct a Driver from an already-validated users-table row."""
        super().__init__(user_id, email, password_hash, role="driver", is_active=is_active)
