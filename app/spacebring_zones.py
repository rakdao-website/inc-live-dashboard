"""Mapping between our zones and Spacebring rooms.

Rooms are matched by title, so the same mapping works for the sandbox and
production networks (their resource ids differ, their titles do not).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Zone

# zone_id -> Spacebring resource title
ZONE_TO_SPACEBRING_TITLE: dict[str, str] = {
    "TTS_1": "TikTok LIVE | Main Studio",
    "TTS_2": "TikTok LIVE | Beauty Room",
    "TTS_3": "TikTok LIVE | Music Room",
    "TTS_4": "TikTok LIVE | Battle Room 1",
    "TTS_5": "TikTok LIVE | Battle Room 2",
    "POD_1": "Podcast Room",
}

# Rooms the TikTok service may book (the kiosk picks one of these).
TIKTOK_ZONE_IDS: tuple[str, ...] = ("TTS_1", "TTS_2", "TTS_3", "TTS_4", "TTS_5")
PODCAST_ZONE_IDS: tuple[str, ...] = ("POD_1",)


def sync_zone_resource_ids(db: Session, rooms: list[dict]) -> dict[str, list[str]]:
    """Set zones.spacebring_resource_id from a Spacebring room list.

    Returns {"mapped": [...], "missing_room": [...], "missing_zone": [...]}.
    """
    by_title = {room.get("title"): room.get("id") for room in rooms}
    result: dict[str, list[str]] = {"mapped": [], "missing_room": [], "missing_zone": []}
    for zone_id, title in ZONE_TO_SPACEBRING_TITLE.items():
        zone = db.get(Zone, zone_id)
        if zone is None:
            result["missing_zone"].append(zone_id)
            continue
        resource_id = by_title.get(title)
        if resource_id is None:
            result["missing_room"].append(f"{zone_id} ({title})")
            continue
        zone.spacebring_resource_id = resource_id
        result["mapped"].append(f"{zone_id} -> {title}")
    db.commit()
    return result
