"""
models/owner.py -- Owner subclass of User.

No role-specific fields yet: none of the design docs (Modules 2, 4, 6-9, 12)
define an Owner data dictionary distinct from User -- owners simply get full
access to every BreadFlow function (FR-A3), which the base User class
already expresses via `role == "owner"`. This class exists from Module 1
onward so the OOP hierarchy (User -> Owner/Client/Driver) is in place, and
so there's already a natural place to add owner-specific fields if a later
module needs one.
"""

from models.user import User


class Owner(User):
    """An Owner is a User with role='owner' and no additional fields (yet)."""

    def __init__(self, user_id, email, password_hash, is_active):
        """Construct an Owner from an already-validated users-table row."""
        super().__init__(user_id, email, password_hash, role="owner", is_active=is_active)
