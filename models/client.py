# models/client.py -- Client subclass of User; business fields live in the clients table.

import datetime
import re
import sqlite3

import bcrypt

from database.db import get_db_connection
from models.order import WEEKDAYS
from models.user import EMAIL_PATTERN, MAX_EMAIL_LENGTH, MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH, User

ZONES = ("Western", "Northern", "Eastern", "Southern")  # matches clients.delivery_zone CHECK
ABN_PATTERN = re.compile(r"^\d{11}$")
MAX_BUSINESS_NAME_LENGTH = 100  # data dictionary: "Max 100 chars"


# FR-A2 registration failure: bad input, or a uniqueness clash on email/business_name/abn.
class ClientValidationError(Exception):
    pass


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

        return cls._from_joined_row(row)

    # Builds a Client by joining users+clients on clients.client_id (Module A: list/deactivate).
    @classmethod
    def load_by_client_id(cls, client_id):
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
                WHERE clients.client_id = ?
                """,
                (client_id,),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            raise ValueError(f"No clients row found for client_id={client_id}")

        return cls._from_joined_row(row)

    # Module A: owner's client list -- every client, A-Z by business name.
    @classmethod
    def list_all(cls):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                """
                SELECT users.user_id, users.email, users.password_hash, users.is_active,
                       users.login_at,
                       clients.client_id, clients.business_name, clients.abn,
                       clients.delivery_zone, clients.delivery_day1, clients.delivery_day2,
                       clients.delivery_charge, clients.internal_notes
                FROM users
                JOIN clients ON clients.user_id = users.user_id
                ORDER BY clients.business_name ASC
                """
            ).fetchall()
        finally:
            connection.close()

        return [cls._from_joined_row(row) for row in rows]

    # Shared users+clients row -> Client builder, used by all three loaders above.
    @staticmethod
    def _from_joined_row(row):
        return Client(
            user_id=row["user_id"], email=row["email"], password_hash=row["password_hash"],
            is_active=row["is_active"], client_id=row["client_id"],
            business_name=row["business_name"], abn=row["abn"],
            delivery_zone=row["delivery_zone"], delivery_day1=row["delivery_day1"],
            delivery_day2=row["delivery_day2"], delivery_charge=row["delivery_charge"],
            internal_notes=row["internal_notes"], login_at=row["login_at"],
        )

    # ---- registration (FR-A2/FR-B2) --------------------------------------

    # Owner-side client registration: creates the users+clients rows and the initial
    # product catalogue in one transaction. Raises ClientValidationError on any bad
    # input, including uniqueness clashes (email/business_name/abn) caught from the DB.
    @classmethod
    def create(cls, business_name, abn, email, temp_password, delivery_zone,
               delivery_day1, delivery_day2, delivery_charge, product_selections,
               internal_notes=None):
        business_name = (business_name or "").strip()
        abn = (abn or "").strip()
        email = (email or "").strip()
        internal_notes = (internal_notes or "").strip() or None

        # -- existence / type ------------------------------------------------
        if not business_name or not abn or not email or not temp_password:
            raise ClientValidationError("Please fill in all required fields")
        if not isinstance(product_selections, list) or not product_selections:
            raise ClientValidationError("Select at least one approved product")

        # -- range / reasonableness ------------------------------------------
        if len(business_name) > MAX_BUSINESS_NAME_LENGTH:
            raise ClientValidationError("Business name is too long")
        if len(email) > MAX_EMAIL_LENGTH:
            raise ClientValidationError("Enter a valid email address")
        if len(temp_password) < MIN_PASSWORD_LENGTH:
            raise ClientValidationError(f"Temporary password must be at least {MIN_PASSWORD_LENGTH} characters")
        if len(temp_password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ClientValidationError("Temporary password is too long")

        # -- format -----------------------------------------------------
        if not EMAIL_PATTERN.match(email):
            raise ClientValidationError("Enter a valid email address")
        if not ABN_PATTERN.match(abn):
            raise ClientValidationError("ABN must be exactly 11 digits")
        if delivery_zone not in ZONES:
            raise ClientValidationError("Select a valid delivery zone")
        if delivery_day1 not in WEEKDAYS or delivery_day2 not in WEEKDAYS:
            raise ClientValidationError("Select valid delivery days")
        if delivery_day1 == delivery_day2:
            raise ClientValidationError("Delivery days must be different")

        try:
            delivery_charge = float(delivery_charge)
        except (TypeError, ValueError):
            raise ClientValidationError("Enter a valid delivery charge")
        if delivery_charge <= 0:
            raise ClientValidationError("Delivery charge must be greater than zero")

        for selection in product_selections:
            if selection["agreed_price"] <= 0 or selection["pack_size"] <= 0:
                raise ClientValidationError("Product prices and pack sizes must be greater than zero")

        # -- persist -----------------------------------------------------
        password_hash = bcrypt.hashpw(temp_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        connection = get_db_connection()
        try:
            user_cursor = connection.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'client')",
                (email, password_hash),
            )
            new_user_id = user_cursor.lastrowid

            client_cursor = connection.execute(
                """
                INSERT INTO clients (user_id, business_name, abn, delivery_zone,
                                      delivery_day1, delivery_day2, delivery_charge, internal_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_user_id, business_name, abn, delivery_zone, delivery_day1,
                 delivery_day2, delivery_charge, internal_notes),
            )
            new_client_id = client_cursor.lastrowid

            for selection in product_selections:
                connection.execute(
                    """
                    INSERT INTO client_products (client_id, product_id, agreed_price, pack_size)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_client_id, selection["product_id"], selection["agreed_price"], selection["pack_size"]),
                )

            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            message = str(exc)
            if "users.email" in message:
                raise ClientValidationError("That email address is already registered")
            if "clients.business_name" in message:
                raise ClientValidationError("That business name is already registered")
            if "clients.abn" in message:
                raise ClientValidationError("That ABN is already registered")
            raise ClientValidationError("Could not save this client -- check the entered details")
        finally:
            connection.close()

        return cls.load_by_user_id(new_user_id)

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

    # ---- catalogue management (Module 12, owner edit) ---------------------

    # Replaces this client's entire client_products set in one transaction -- delete-then-
    # reinsert is the simplest correct approach, since client_products has no soft-delete
    # flag and no per-row edit history is required. Scoped entirely by self._client_id,
    # so it can never touch another client's rows or products.base_price.
    def update_product_catalogue(self, product_selections):
        if not isinstance(product_selections, list) or not product_selections:
            raise ClientValidationError("Select at least one product for this client's catalogue")
        for selection in product_selections:
            if selection["agreed_price"] <= 0 or selection["pack_size"] <= 0:
                raise ClientValidationError("Product prices and pack sizes must be greater than zero")

        connection = get_db_connection()
        try:
            connection.execute("DELETE FROM client_products WHERE client_id = ?", (self._client_id,))
            for selection in product_selections:
                connection.execute(
                    """
                    INSERT INTO client_products (client_id, product_id, agreed_price, pack_size)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self._client_id, selection["product_id"], selection["agreed_price"], selection["pack_size"]),
                )
            connection.commit()
        finally:
            connection.close()

    # ---- dashboard reminder (FR-F3, rule-based, no AI) ---------------------

    # Flags active clients overdue for their next order: daysSinceOrder > avgInterval * 1.5,
    # where avgInterval is the average gap across their last 10 approved/delivered orders
    # (fallback 7 days when there's fewer than 2, since that's roughly one of their 2
    # fixed weekly delivery days). Never-ordered clients are always flagged. Sorted by
    # how overdue they are relative to their own pattern, most overdue first.
    @classmethod
    def get_overdue_clients(cls):
        connection = get_db_connection()
        try:
            flagged = []
            for client in cls.list_all():
                if not client.is_active:
                    continue

                rows = connection.execute(
                    """
                    SELECT delivery_date FROM orders
                    WHERE client_id = ? AND order_status IN ('approved', 'delivered')
                    ORDER BY delivery_date DESC LIMIT 10
                    """,
                    (client.client_id,),
                ).fetchall()

                dates = [datetime.date.fromisoformat(row["delivery_date"]) for row in rows]
                days_since_order = (datetime.date.today() - dates[0]).days if dates else None

                if len(dates) >= 2:
                    gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
                    avg_interval = sum(gaps) / len(gaps)
                else:
                    avg_interval = 7

                if days_since_order is None or days_since_order > avg_interval * 1.5:
                    flagged.append({
                        "client_id": client.client_id,
                        "business_name": client.business_name,
                        "delivery_days": client.delivery_days,
                        "days_since_order": days_since_order,
                        "avg_interval": round(avg_interval),
                    })
        finally:
            connection.close()

        flagged.sort(
            key=lambda entry: (float("inf") if entry["days_since_order"] is None
                                else entry["days_since_order"] / entry["avg_interval"]),
            reverse=True,
        )
        return flagged

    # ---- session -----------------------------------------------------

    # Also stores client_id -- routes need it without an extra query.
    def get_session(self):
        session_data = super().get_session()
        session_data["client_id"] = self._client_id
        return session_data
