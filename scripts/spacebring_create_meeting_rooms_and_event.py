"""Create Meeting Room 1, Meeting Room 2 and one free event in Spacebring (sandbox by default).

Safe to run again: a room or event whose title already exists is skipped.
Usage: python scripts/spacebring_create_meeting_rooms_and_event.py --photo1 PATH --photo2 PATH
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.spacebring_client import SpacebringError, get_spacebring_client, to_spacebring_datetime  # noqa: E402

# Settings copied from an existing room so the new ones behave the same (opening days, durations, booking rules).
COPY_FROM_EXISTING = ("schedule", "duration", "bookingWindow", "bookingStepMinutes", "bookingUnit", "bufferTime",
                      "preparationMinutes", "refundThreshold", "dayPassesEnabled")
DUBAI = timezone(timedelta(hours=4))

ROOMS = [
    {"title": "Meeting Room 1", "capacity": 6, "photo": "photo1"},
    {"title": "Meeting Room 2", "capacity": 5, "photo": "photo2"},
]


def upload_photo(client, path: Path) -> dict:
    """Spacebring media flow: ask for an upload slot, PUT the file to it, then attach the returned key."""
    data = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    media = client._request("POST", "/resources/v1/media", json={"media": {"mimeType": mime, "size": len(data)}})["media"]
    upload = media["upload"]
    put = httpx.put(upload["url"], content=data, headers=upload["headers"], timeout=30)
    put.raise_for_status()
    return {"key": media["key"], "mimeType": mime, "size": len(data)}


def attach_photo(client, resource_id: str, media: dict) -> None:
    """Spacebring takes a moment to register the uploaded file, so retry for a few seconds."""
    for attempt in range(10):
        try:
            client._request("PATCH", f"/resources/v1/{resource_id}", json={"resource": {"media": [media]}})
            return
        except SpacebringError as exc:
            if "not finished" not in str(exc) or attempt == 9:
                raise
            time.sleep(1.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--photo1", type=Path)
    parser.add_argument("--photo2", type=Path)
    args = parser.parse_args()
    photos = {"photo1": args.photo1, "photo2": args.photo2}

    print(f"Spacebring environment: {settings.spacebring_environment}")
    client = get_spacebring_client()
    rooms = client.list_rooms()
    template = next((r for r in rooms if r.get("title") == "Podcast Room"), rooms[0])
    existing = {r["title"]: r for r in rooms}

    for spec in ROOMS:
        photo = photos[spec["photo"]]
        found = existing.get(spec["title"])
        if found is not None:
            if photo and not found.get("media"):
                media = upload_photo(client, photo)
                attach_photo(client, found['id'], media)
                print(f"photo  {spec['title']} (room already existed, photo added)")
            else:
                print(f"skip   {spec['title']} (already exists)")
            continue
        body = {k: template[k] for k in COPY_FROM_EXISTING if k in template}
        body.update(locationRef=client.location_id, title=spec["title"], type="meetingRoom", capacity=spec["capacity"],
                    visibility="public", bookingPermission=template.get("bookingPermission", "public"))
        created = client._request("POST", "/resources/v1", json={"resource": body})["resource"]
        print(f"create {spec['title']} -> {created['id']}")
        if photo:
            media = upload_photo(client, photo)
            attach_photo(client, created['id'], media)
            print("  photo attached")

    events = client._request("GET", "/events/v1", params={"locationRef": client.location_id, "limit": 100}).get("events", [])
    title = "Innovation City Community Meetup"
    if any(e.get("title") == title for e in events):
        print(f"skip   event {title} (already exists)")
        return
    start = (datetime.now(DUBAI) + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    event = {
        "title": title,
        "description": "A free community meetup at Innovation City. Meet other members and see the spaces. Everyone is welcome.",
        "locationRef": client.location_id,
        "startDate": to_spacebring_datetime(start),
        "endDate": to_spacebring_datetime(start + timedelta(hours=2)),
        "applicationType": "none",
        "visibility": "public",
        "venue": "Innovation City",
    }
    created = client._request("POST", "/events/v1", json={"event": event})
    print("create event ->", (created.get("event") or created).get("id"))


if __name__ == "__main__":
    main()
