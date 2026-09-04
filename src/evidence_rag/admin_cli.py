"""Command-line bootstrap utilities for Hujjat AI administration."""

import argparse
import getpass
import os
from pathlib import Path

from .admin_service import AdminService
from .admin_store import AdminStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first Hujjat AI superadmin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Super Admin")
    parser.add_argument("--database", type=Path, default=Path("data/admin.db"))
    parser.add_argument("--knowledge", type=Path, default=Path("knowledge"))
    args = parser.parse_args()
    password = os.getenv("HUJJAT_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    service = AdminService(AdminStore(args.database), args.knowledge)
    user_id = service.bootstrap_superadmin(args.email, password, args.name)
    print(f"Superadmin is ready (user id: {user_id}).")


if __name__ == "__main__":
    main()
