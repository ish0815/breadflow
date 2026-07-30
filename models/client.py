# models/client.py -- Client subclass of User; business fields live in the clients table.

from database.db import get_db_connection
from models.user import User


# A User (role='client') plus their clients-table row: ABN, delivery zone/days/charge, notes.
class Client(User):

    # Role is fixed to 'client', never a parameter -- can't construct with the wrong role.
    def __init__(self, user_id, email, password_hash, is_active,
                 client_id, business_name, abn, delivery_zone,
                 delivery_day1, delivery_day2, delivery_charge,
                 internal_notes=None, login_at=None):
        super().__init__(user_id, email, password_hash, role="client",
                          is_active=is_active, login_at=login_at)

        self._client_id = client_id
        self._business_name = business_name
        self._abn = abn
        self._delivery_zone = delivery_zone
        self._delivery_day1 = delivery_day1
        self._delivery_day2 = delivery_day2
        self._delivery_charge = delivery_charge
        self._internal_notes = internal_notes

    # ---- read-only accessors --------------------------------------------

    # Primary key on the `clients` table -- the FK target used by orders, invoices, etc.
    @property
    def client_id(self):
        return self._client_id

    # Trading name shown on invoices, dashboards, and delivery dockets.
    @property
    def business_name(self):
        return self._business_name

    # 11-digit Australian Business Number. Required for invoice compliance.
    @property
    def abn(self):
        return self._abn

    # One of Western | Northern | Eastern | Southern -- drives FR-B1/production routing.
    @property
    def delivery_zone(self):
        return self._delivery_zone

    # Tuple of this client's two fixed weekly delivery days (FR-B1).
    @property
    def delivery_days(self):
        return (self._delivery_day1, self._delivery_day2)

    # Flat per-order delivery fee for this client. GST applies to this line only (FR-D1).
    @property
    def delivery_charge(self):
        return self._delivery_charge

    # Owner-only annotation about this client. Must never be rendered in the client portal.
    @property
    def internal_notes(self):
        return self._internal_notes

    # ---- construction from the database ----------------------------------

    # Builds a Client by joining users+clients on user_id. Reuses `connection` if given.
    @classmethod
    def load_by_user_id(cls, user_id, connection=None):
        owns_connection = connection is None
        if connection is None:
            connection = get_db_connection()

        try:
            row = connection.execute(
                """
                SELECT users.user_id, users.email, users.password_hash, users.is_active,
                       users.login_at,
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
            # integrity bug if this happens -- fail loudly, don't return None
            raise ValueError(f"No clients row found for user_id={user_id}")

        return cls(
            user_id=row["user_id"], email=row["email"], password_hash=row["password_hash"],
            is_active=row["is_active"], client_id=row["client_id"],
            business_name=row["business_name"], abn=row["abn"],
            delivery_zone=row["delivery_zone"], delivery_day1=row["delivery_day1"],
            delivery_day2=row["delivery_day2"], delivery_charge=row["delivery_charge"],
            internal_notes=row["internal_notes"], login_at=row["login_at"],
        )

    # ---- ordering (FR-B1/B2) --------------------------------------------

    # FR-B2: only approved products show up here (joined through client_products).
    def get_approved_products(self):
        connection = get_db_connection()
        try:
            return connection.execute(
                """
                SELECT products.product_id, products.product_name, products.category,
                       client_products.agreed_price, client_products.pack_size
                FROM client_products
                JOIN products ON products.product_id = client_products.product_id
                WHERE client_products.client_id = ?
                ORDER BY products.category, products.product_name
                """,
                (self._client_id,),
            ).fetchall()
        finally:
            connection.close()

    # ---- session -----------------------------------------------------

    # Also stores client_id -- routes need it without an extra query.
    def get_session(self):
        session_data = super().get_session()
        session_data["client_id"] = self._client_id
        return session_data
