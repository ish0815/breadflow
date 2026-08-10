# models/delivery.py -- Delivery: FR-E1/FR-E2 driver docket, one row per approved order.

from database.db import get_db_connection


# create() called on a bad order/driver (not approved, not an active driver).
class DeliveryValidationError(Exception):
    pass


# mark_delivered() called on a delivery that's already delivered.
class DeliveryStateError(Exception):
    pass


# One approved order's delivery assignment: driver, date, status, proof of delivery.
class Delivery:

    def __init__(self, delivery_id, order_id, driver_id, delivery_date, delivery_status,
                 proof_photo_path=None, delivered_at=None, special_instructions=None):
        self._delivery_id = delivery_id
        self._order_id = order_id
        self._driver_id = driver_id
        self._delivery_date = delivery_date
        self._delivery_status = delivery_status
        self._proof_photo_path = proof_photo_path
        self._delivered_at = delivered_at
        self._special_instructions = special_instructions

    # ---- read-only accessors ----------------------------------------------

    @property
    def delivery_id(self):
        return self._delivery_id

    @property
    def order_id(self):
        return self._order_id

    @property
    def driver_id(self):
        return self._driver_id

    @property
    def delivery_date(self):
        return self._delivery_date

    @property
    def delivery_status(self):
        return self._delivery_status

    @property
    def proof_photo_path(self):
        return self._proof_photo_path

    @property
    def delivered_at(self):
        return self._delivered_at

    @property
    def special_instructions(self):
        return self._special_instructions

    # ---- creation (owner assigns a driver to an approved order) -----------------

    # FR-E1: order must exist and be approved; driver must be an active user with
    # role='driver' -- both un-expressible as a DB CHECK, so validated here instead.
    # delivery_date/special_instructions are copied from the order, never caller-supplied,
    # so a delivery can't drift from the order it belongs to.
    @classmethod
    def create(cls, order_id, driver_id):
        connection = get_db_connection()
        try:
            order_row = connection.execute(
                "SELECT delivery_date, special_instructions, order_status FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if order_row is None or order_row["order_status"] != "approved":
                raise DeliveryValidationError(
                    "Order must exist and be approved before a delivery can be assigned"
                )

            driver_row = connection.execute(
                "SELECT role, is_active FROM users WHERE user_id = ?", (driver_id,)
            ).fetchone()
            if driver_row is None or driver_row["role"] != "driver" or not driver_row["is_active"]:
                raise DeliveryValidationError("Assigned user must be an active driver")

            cursor = connection.execute(
                """
                INSERT INTO deliveries (order_id, driver_id, delivery_date, special_instructions)
                VALUES (?, ?, ?, ?)
                """,
                (order_id, driver_id, order_row["delivery_date"], order_row["special_instructions"]),
            )
            delivery_id = cursor.lastrowid
            connection.commit()
            row = connection.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
            ).fetchone()
            return cls._build_from_row(row)
        finally:
            connection.close()

    # ---- reading back ------------------------------------------------------

    # FR-E1: today's (or any date's) docket for one driver. Ordered by delivery_id --
    # true stop-sequence ordering is a later commit (route/zone logic, not modelled yet).
    @classmethod
    def get_by_driver_and_date(cls, driver_id, delivery_date):
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM deliveries WHERE driver_id = ? AND delivery_date = ? ORDER BY delivery_id ASC",
                (driver_id, delivery_date),
            ).fetchall()
        finally:
            connection.close()
        return [cls._build_from_row(row) for row in rows]

    @classmethod
    def get_by_id(cls, delivery_id):
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
            ).fetchone()
        finally:
            connection.close()
        return cls._build_from_row(row) if row else None

    # ---- lifecycle (FR-E2) --------------------------------------------------

    # Sets delivery_status='delivered' + delivered_at=now(). Requires a photo path --
    # full upload validation (JPEG/PNG, <=10MB) belongs to the route, not this method.
    def mark_delivered(self, proof_photo_path):
        if not proof_photo_path or not isinstance(proof_photo_path, str):
            raise DeliveryValidationError("A proof-of-delivery photo is required")

        connection = get_db_connection()
        try:
            # only matches if still pending -- blocks a double mark-delivered
            cursor = connection.execute(
                """
                UPDATE deliveries SET delivery_status = 'delivered', proof_photo_path = ?,
                                       delivered_at = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now')
                WHERE delivery_id = ? AND delivery_status = 'pending'
                """,
                (proof_photo_path, self._delivery_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT proof_photo_path, delivered_at FROM deliveries WHERE delivery_id = ?",
                (self._delivery_id,),
            ).fetchone()
        finally:
            connection.close()

        if cursor.rowcount == 0:
            raise DeliveryStateError("This delivery has already been marked as delivered")

        self._delivery_status = "delivered"
        self._proof_photo_path = row["proof_photo_path"]
        self._delivered_at = row["delivered_at"]

    @staticmethod
    def _build_from_row(row):
        return Delivery(
            row["delivery_id"], row["order_id"], row["driver_id"], row["delivery_date"],
            row["delivery_status"], row["proof_photo_path"], row["delivered_at"],
            row["special_instructions"],
        )
