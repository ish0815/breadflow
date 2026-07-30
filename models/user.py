# models/user.py -- User: base class for Owner/Client/Driver. One users table for FR-A1/FR-A3 login.

import re

import bcrypt

from database.db import get_db_connection

# simple email check -- catches typos, not a strict RFC 5322 match
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_EMAIL_LENGTH = 254      # data dictionary: "Max 254 chars"
MIN_PASSWORD_LENGTH = 8     # data dictionary: "Min 8 characters"
MAX_PASSWORD_BYTES = 72     # bcrypt silently truncates past 72 bytes


# Base class for FR-A1 login failures; never raised directly.
class AuthenticationError(Exception):
    pass


# Bad input (empty/malformed) before any DB query.
class ValidationError(AuthenticationError):
    pass


# No such account, or wrong password -- same message either way (NF-08, no enumeration).
class InvalidCredentialsError(AuthenticationError):
    pass


# Correct password, but the account is deactivated.
class AccountDeactivatedError(AuthenticationError):
    pass


# Base class for Owner/Client/Driver -- holds only login/role fields (FR-A1/FR-A3).
class User:

    # Construct a User from already-validated data (a trusted database row).
    # Never called directly with raw form input -- see User.authenticate().
    def __init__(self, user_id, email, password_hash, role, is_active=True, login_at=None):
        # protected not private -- subclasses need direct access, external code uses the properties below
        self._user_id = user_id
        self._email = email
        self._password_hash = password_hash  # bcrypt hash only -- NF-06, never plaintext
        self._role = role
        self._is_active = bool(is_active)  # SQLite stores 0/1; normalise to a real bool in Python
        self._login_at = login_at  # ISO 8601 string, or None if never logged in

    # ---- read-only accessors --------------------------------------------
    # properties, not public attributes -- user_id/role must never be reassigned

    # Integer primary key from the users table. Read-only.
    @property
    def user_id(self):
        return self._user_id

    # Login email address. Read-only after construction.
    @property
    def email(self):
        return self._email

    # One of 'owner' | 'client' | 'driver'. Drives FR-A3 role-based access control.
    @property
    def role(self):
        return self._role

    # False once an owner has called deactivate() on this account.
    @property
    def is_active(self):
        return self._is_active

    # Last successful login timestamp, or None. Set server-side only.
    @property
    def login_at(self):
        return self._login_at

    # ---- authentication --------------------------------------------------

    # FR-A1 login: checks email/password, returns a typed Owner/Client/Driver.
    @classmethod
    def authenticate(cls, email, password):
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

        # too short to match any real hash -- skip the slow bcrypt call
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidCredentialsError("Invalid email or password")

        connection = get_db_connection()
        try:
            # COLLATE NOCASE avoids relying on every write path to lower-case emails
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

            # FR-A1: record this login, using the DB's own clock not the app server's
            connection.execute(
                "UPDATE users SET login_at = STRFTIME('%Y-%m-%dT%H:%M:%S', 'now') WHERE user_id = ?",
                (row["user_id"],),
            )
            connection.commit()
            # re-read to pick up the login_at we just set
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?", (row["user_id"],)
            ).fetchone()

            return cls._build_from_row(row, connection)
        finally:
            # closed here, after _build_from_row() is done with it
            connection.close()

    # Builds the right subclass for a users row; Client needs a joined second query.
    @staticmethod
    def _build_from_row(row, connection):
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
        # unreachable -- role has a CHECK constraint
        raise ValueError(f"Unknown role '{role}' on users table")

    # ---- session -----------------------------------------------------

    # Session dict for FR-A1 (userID + role) -- plain dict, Flask-agnostic.
    def get_session(self):
        return {"user_id": self._user_id, "role": self._role}

    # ---- lifecycle -----------------------------------------------------

    # Disables the account (Module 7) -- updates DB and this instance together.
    def deactivate(self):
        connection = get_db_connection()
        try:
            connection.execute(
                "UPDATE users SET is_active = 0 WHERE user_id = ?", (self._user_id,)
            )
            connection.commit()
        finally:
            connection.close()
        self._is_active = False
