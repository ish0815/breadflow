"""
models/client.py -- Client subclass of User.

Represents a B2B customer account (restaurant, cafe, retailer). Inherits
login/session/deactivation behaviour from User, but ALL of its
business-specific fields (business_name, abn, delivery_zone, etc.) live in
the separate `clients` table, joined on user_id -- not as extra columns on
`users`. This mirrors how every other module (Orders, Invoices,
ClientCatalogue) already treats clientID as its own foreign key, and keeps
`users` a pure authentication table shared by all three roles.
"""

from database.db import get_db_connection
from models.user import User


class Client(User):
    """
    A Client is a User (role='client') plus the row from `clients` that
    describes their business: ABN, assigned delivery zone/days, delivery
    charge, and any internal notes an owner has recorded about them.
    """

    def __init__(self, user_id, email, password_hash, is_active,
                 client_id, business_name, abn, delivery_zone,
                 delivery_day1, delivery_day2, delivery_charge,
                 internal_notes=None):
        """Construct a Client from an already-validated, joined users+clients row.
        `role` is fixed to 'client' rather than accepted as a parameter, so it's
        impossible to construct a Client instance with the wrong role by mistake."""
        super().__init__(user_id, email, password_hash, role="client", is_active=is_active)

        self._client_id = client_id
        self._business_name = business_name
        self._abn = abn
        self._delivery_zone = delivery_zone
        self._delivery_day1 = delivery_day1
        self._delivery_day2 = delivery_day2
        self._delivery_charge = delivery_charge
        self._internal_notes = internal_notes

    # ---- read-only accessors --------------------------------------------

    @property
    def client_id(self):
        """Primary key on the `clients` table -- the FK target used by orders, invoices, etc."""
        return self._client_id

    @property
    def business_name(self):
        """Trading name shown on invoices, dashboards, and delivery dockets."""
        return self._business_name

    @property
    def abn(self):
        """11-digit Australian Business Number. Required for invoice compliance."""
        return self._abn

    @property
    def delivery_zone(self):
        """One of Western | Northern | Eastern | Southern -- drives FR-B1/production routing."""
        return self._delivery_zone

    @property
    def delivery_days(self):
        """Tuple of this client's two fixed weekly delivery days (FR-B1)."""
        return (self._delivery_day1, self._delivery_day2)

    @property
    def delivery_charge(self):
        """Flat per-order delivery fee for this client. GST applies to this line only (FR-D1)."""
        return self._delivery_charge

    @property
    def internal_notes(self):
        """Owner-only annotation about this client. Must never be rendered in the client portal."""
        return self._internal_notes

    # ---- construction from the database ----------------------------------

    @classmethod
    def load_by_user_id(cls, user_id, connection=None):
        """
        Builds a Client by joining `users` and `clients` on user_id.

        Called from User.authenticate() once it knows role == 'client', and
        reused directly by Module 7 (Clients Management) whenever a client
        needs to be loaded outside of a login attempt.

        Accepts an optional existing `connection` so authenticate() can
        reuse the connection it already opened instead of every layer
        opening its own; when no connection is supplied, this method opens
        and closes one itself so it also works as a standalone call.
        """
        owns_connection = connection is None
        if connection is None:
            connection = get_db_connection()

        try:
            row = connection.execute(
                """
                SELECT users.user_id, users.email, users.password_hash, users.is_active,
                       clients.client_id, clients.business_name, clients.abn,
                       clients.delivery_zone, clients.delivery_day1, clients.delivery_day2,
                       clients.delivery_charge, clients.internal_notes
                FROM users
                JOIN clients ON clients.user_id = users.user_id
                WHERE users.user_id = ?
                """,
                (user_id,),
            ).fetchone()
        finally:
            if owns_connection:
                connection.close()

        if row is None:
            # A users row with role='client' but no matching clients row is
            # a data-integrity bug (client creation should always insert
            # both rows in one transaction), not a user input error -- so
            # this fails loudly instead of silently returning None.
            raise ValueError(f"No clients row found for user_id={user_id}")

        return cls(
            user_id=row["user_id"], email=row["email"], password_hash=row["password_hash"],
            is_active=row["is_active"], client_id=row["client_id"],
            business_name=row["business_name"], abn=row["abn"],
            delivery_zone=row["delivery_zone"], delivery_day1=row["delivery_day1"],
            delivery_day2=row["delivery_day2"], delivery_charge=row["delivery_charge"],
            internal_notes=row["internal_notes"],
        )

    # ---- session -----------------------------------------------------

    def get_session(self):
        """
        Extends User.get_session() to also store client_id: every client
        route (Modules 3 and 10) filters queries by clientID, so it needs
        to be available from the session directly rather than re-derived
        from user_id with an extra database query on every request.
        """
        session_data = super().get_session()
        session_data["client_id"] = self._client_id
        return session_data
