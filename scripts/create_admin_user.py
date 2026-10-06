"""Create (or reset the password of) an admin panel user.

    python scripts/create_admin_user.py --username alice --role super_user

The password is read from a hidden prompt (or ADMIN_NEW_PASSWORD for automation),
never from the command line, so it does not land in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.admin_panel.models import AdminUser  # noqa: E402
from app.admin_panel.permissions import ROLES  # noqa: E402
from app.admin_panel.security import hash_password, password_problem  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--role", choices=ROLES, default="super_user")
    parser.add_argument("--reset-password", action="store_true", help="update the password of an existing user")
    args = parser.parse_args()

    password = os.environ.get("ADMIN_NEW_PASSWORD") or getpass.getpass("Password: ")
    if not os.environ.get("ADMIN_NEW_PASSWORD") and getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.")
        return 1
    problem = password_problem(password)
    if problem:
        print(problem)
        return 1

    Base.metadata.create_all(bind=engine, tables=[AdminUser.__table__])
    username = args.username.strip().lower()
    with SessionLocal() as db:
        user = db.query(AdminUser).filter(AdminUser.username == username).one_or_none()
        if user is not None and not args.reset_password:
            print(f"User '{username}' already exists. Use --reset-password to change the password.")
            return 1
        if user is None:
            user = AdminUser(username=username, display_name=args.display_name or username, role=args.role, password_hash="")
            db.add(user)
        user.password_hash = hash_password(password)
        user.is_active = True
        role = user.role
        db.commit()
    print(f"Saved admin user '{username}' ({role}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
