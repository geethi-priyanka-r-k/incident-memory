"""Create a local login account without saving a plaintext password."""

from __future__ import annotations

import getpass
import re
import sqlite3
import sys

from settings import load_env

load_env()

from werkzeug.security import generate_password_hash

import db


def main() -> int:
    db.initialize()
    name = input("Name: ").strip()
    email = input("Email: ").strip()
    if not name or len(name) > 100:
        print("Enter a name between 1 and 100 characters.")
        return 1
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        print("Enter a valid email address.")
        return 1

    password = getpass.getpass("Password (12 characters minimum): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        print("Use a password with at least 12 characters.")
        return 1
    if password != confirmation:
        print("The passwords did not match.")
        return 1

    try:
        db.create_user(name, email, generate_password_hash(password))
    except sqlite3.IntegrityError:
        print("An account already exists with that email address.")
        return 1
    print("User created. Sign in with the email address you entered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
