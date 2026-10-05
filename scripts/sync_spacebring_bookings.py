"""Pull upcoming Spacebring bookings into Postgres once.

Usage:  .venv/bin/python -m scripts.sync_spacebring_bookings
(The API also runs this every SPACEBRING_SYNC_INTERVAL_SECONDS while it is up.)
"""
from app.database import SessionLocal
from app.spacebring_client import get_spacebring_client
from app.spacebring_sync import sync_bookings


def main() -> None:
    with SessionLocal() as db:
        result = sync_bookings(db, get_spacebring_client())
    print(f"Spacebring sync: {result}")
    for item in result.skipped:
        print(f"  skipped: {item}")


if __name__ == "__main__":
    main()
