"""Link zones to Spacebring rooms (run after the migration).

Usage:  .venv/bin/python -m scripts.sync_spacebring_zones
Uses the SPACEBRING_* settings from .env (sandbox or production).
"""
from app.database import SessionLocal
from app.spacebring_client import get_spacebring_client
from app.spacebring_zones import sync_zone_resource_ids


def main() -> None:
    rooms = get_spacebring_client().list_rooms()
    print(f"Spacebring rooms found: {len(rooms)}")
    with SessionLocal() as db:
        result = sync_zone_resource_ids(db, rooms)
    for key, items in result.items():
        print(f"{key}:")
        for item in items:
            print(f"  {item}")


if __name__ == "__main__":
    main()
