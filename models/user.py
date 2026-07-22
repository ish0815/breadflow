"""
models/user.py -- User: the base class shared by every BreadFlow account.

Why a single `users` table backs all three roles (FR-A3):
login only ever needs email + password + role to route someone to the
correct dashboard. Splitting login credentials across three separate
tables would mean the FR-A1 login query has to guess which table to check
before it even knows who the user is. Keeping one `users` table means
FR-A1 is always a single lookup, while role-specific business data (e.g. a
client's ABN and delivery zone) lives in its own table, joined on user_id --
matching how every other module (orders, invoices, client_products)
already references clientID as a foreign key in its own right, not as a
column on users.
"""

import re

import bcrypt

from database.db import get_db_connection

# Matches the data dictionary's "Valid email format" constraint: something,
# an @, something, a dot, something. Deliberately simple rather than a
# full RFC 5322 pattern -- BreadFlow's clients are time-poor business
# owners entering their own real work email, not adversarial input, so a
# pattern that catches obvious typos (missing @, missing domain) is more
# useful than one that rejects legitimate-but-unusual addresses.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_EMAIL_LENGTH = 254      # data dictionary: "Max 254 chars"
MIN_PASSWORD_LENGTH = 8     # data dictionary: "Min 8 characters"
# bcrypt silently truncates any input past 72 BYTES and hashes the rest --
# two different passwords that share the same first 72 bytes would produce
# the same hash. Rejecting long input outright is safer than letting that
# happen unnoticed.
MAX_PASSWORD_BYTES = 72


class AuthenticationError(Exception):
    """Base class for every FR-A1 login failure. Never raised directly --
    always one of the specific subclasses below, so calling code can either
    catch this one type generically or handle each case separately."""


class ValidationError(AuthenticationError):
    """
    Raised when the submitted email/password fail basic input validation
    (empty, wrong type, or badly formatted) -- before any database query
    is attempted. Corresponds to the pseudocode's "Please fill in all
    required fields" and "Enter a valid email address" branches.
    """


class InvalidCredentialsError(AuthenticationError):
    """
    Raised when the email does not match any account, OR the password is
    wrong for an account that does exist. Both cases share one message
    ("Invalid email or password") deliberately -- confirming that an email
    exists but the password was wrong would let an attacker enumerate
    which businesses are registered as Bread Staple clients.
    """


class AccountDeactivatedError(AuthenticationError):
    """Raised when the password is correct but an owner has set isActive = False
    on this account (Module 7: Client.deactivate() / User.deactivate())."""


class User:
    """
    Base class for every BreadFlow account: Owner, Client, and Driver all
    inherit from this.

    Stores only what login and role-based access control need (FR-A1,
    FR-A3): identity, the bcrypt hash, role, and active status.
    Role-specific data (e.g. a client's business name and delivery zone)
    is deliberately NOT stored here -- it lives on the subclass, backed by
    its own table, because it doesn't apply to every role.
    """

    def __init__(self, user_id, email, password_hash, role, is_active=True, login_at=None):
        """Construct a User from already-validated data (a trusted database row).
        Never called directly with raw form input -- see User.authenticate()."""
        # Single leading underscore (protected, not private): subclasses
        # need direct access to these when building themselves from a
        # joined database row, but external code should always go through
        # the read-only properties below instead of touching these fields.
        self._user_id = user_id
        self._email = email
        self._password_hash = password_hash  # bcrypt hash only -- NF-06, never plaintext
        self._role = role
        self._is_active = bool(is_active)  # SQLite stores 0/1; normalise to a real bool in Python
        self._login_at = login_at  # ISO 8601 string, or None if never logged in

    # ---- read-only accessors --------------------------------------------
    # Exposed as properties rather than public attributes because user_id
    # and role are set once from a trusted database row and must never be
    # reassigned by calling code -- e.g. accidentally overwriting the role
    # that FR-A3 access checks rely on.

    @property
    def user_id(self):
        """Integer primary key from the users table. Read-only."""
        return self._user_id

    @property
    def email(self):
        """Login email address. Read-only after construction."""
        return self._email

    @property
    def role(self):
        """One of 'owner' | 'client' | 'driver'. Drives FR-A3 role-based access control."""
        return self._role

    @property
    def is_active(self):
        """False once an owner has called deactivate() on this account."""
        return self._is_active

    @property
    def login_at(self):
        """ISO 8601 timestamp of this account's most recent successful login,
        or None if it has never logged in. Set server-side only -- see
        User.authenticate()."""
        return self._login_at

    # ---- authentication --------------------------------------------------

    @classmethod
    def authenticate(cls, email, password):
        """
        FR-A1: validate a login attempt and return the fully-typed account.

        Looks up `email` in the users table, verifies `password` against
        the stored bcrypt hash, and returns an Owner, Client, or Driver
        instance (never a bare User) so the caller has role-specific data
        available immediately, without a second query.

        Validates existence, type, and range of both fields before ever
        touching the database (ValidationError), then distinguishes
        "no such account / wrong password" (InvalidCredentialsError) from
        "correct password, but deactivated" (AccountDeactivatedError) --
        matching the four distinct error branches in the FR-A1 pseudocode.
        """
        # -- existence + type ------------------------------------------------
        if not isinstance(email, str) or not isinstance(password, str):
            raise ValidationError("Please fill in all required fields")

        email = email.strip()
        if not email or not password:
            raise ValidationError("Please fill in all required fields")

        # -- range / reasonableness -----------------------------------------
        if len(email) > MAX_EMAIL_LENGTH:
            raise ValidationError("Enter a valid email address")
        if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValidationError("Password is too long")

        # -- format -----------------------------------------------------
        if not EMAIL_PATTERN.match(email):
            raise ValidationError("Enter a valid email address")

        # A genuine account password is always >= 8 characters (enforced
        # wherever passwords are created), so anything shorter can never
        # match a real hash. Rejecting it here avoids a pointless bcrypt
        # verification call, which is intentionally slow by design.
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidCredentialsError("Invalid email or password")

        connection = get_db_connection()
        try:
            # COLLATE NOCASE rather than lower-casing `email` in Python: it
            # compares against whatever case the address was originally
            # stored in, instead of requiring every write path (Module 11's
            # client registration, future owner/driver account creation) to
            # remember to lower-case emails too.
            row = connection.execute(
                "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()

            if row is None:
                raise InvalidCredentialsError("Invalid email or password")

            password_matches = bcrypt.checkpw(
                password.encode("utf-8"), row["password_hash"].encode("utf-8")
            )
            if not password_matches:
                raise InvalidCredentialsError("Invalid email or password")

            if not row["is_active"]:
                raise AccountDeactivatedError(
                    "This account has been deactivated. Contact Bread Staple."
                )

            # FR-A1: record this successful login. STRFTIME('now') is the
            # database's own clock, not the app server's, so login_at is
            # genuinely "set server-side" regardless of where Flask runs --
            # matching the data dictionary's "Cannot be in the future" rule
            # by construction, since the app never accepts this as input.
            connection.execute(
                "UPDATE users SET login_at = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now') WHERE user_id = ?",
                (row["user_id"],),
            )
            connection.commit()
            # Re-read the row so the object we build reflects the login_at
            # value just written, instead of the stale NULL/previous value
            # captured by the SELECT above.
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (row["user_id"],)
            ).fetchone()

            return cls._build_from_row(row, connection)
        finally:
            # Closed here, after _build_from_row() has finished using it,
            # rather than each branch above closing it individually -- one
            # place to reason about connection lifetime instead of a
            # close-before-every-return pattern repeated four times.
            connection.close()

    @staticmethod
    def _build_from_row(row, connection):
        """
        Factory: builds the correctly-typed subclass instance for a users-table row.

        Owner and Driver need nothing beyond the users row -- neither has a
        role-specific table in the design docs -- so they're constructed
        directly. Client rows require a second query against the `clients`
        table, joined on user_id, so that lookup is delegated to
        Client.load_by_user_id().
        """
        role = row["role"]
        if role == "owner":
            from models.owner import Owner
            return Owner(row["user_id"], row["email"], row["password_hash"],
                         row["is_active"], row["login_at"])
        if role == "driver":
            from models.driver import Driver
            return Driver(row["user_id"], row["email"], row["password_hash"],
                          row["is_active"], row["login_at"])
        if role == "client":
            from models.client import Client
            return Client.load_by_user_id(row["user_id"], connection)
        # Defensive, not reachable in normal operation: the `role` column has
        # a CHECK constraint restricting it to owner/client/driver, so this
        # would only fire if the database were modified outside BreadFlow.
        raise ValueError(f"Unknown role '{role}' on users table")

    # ---- session -----------------------------------------------------

    def get_session(self):
        """
        Returns the dict that should be written into Flask's session on a
        successful login (FR-A1: "store userID and role in Flask session").

        Deliberately returns a plain dict rather than touching flask.session
        directly -- this keeps the model layer framework-agnostic; the
        Flask route decides how (and whether) to apply it.
        """
        return {"user_id": self._user_id, "role": self._role}

    # ---- lifecycle -----------------------------------------------------

    def deactivate(self):
        """
        Disables this account (triggered by an owner from Module 7).

        Updates both the database row and this in-memory instance so that
        `is_active` is correct immediately for any code still holding this
        object, not just on the next time it's loaded from the database.
        """
        connection = get_db_connection()
        try:
            connection.execute(
                "UPDATE users SET is_active = 0 WHERE user_id = ?", (self._user_id,)
            )
            connection.commit()
        finally:
            connection.close()
        self._is_active = False
