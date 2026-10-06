"""Room cover photos from Spacebring (public URLs), cached for a few minutes.

The kiosk shows these when a room has a photo in Spacebring and falls back to
its own bundled photos otherwise. A Spacebring outage just means no remote
photos, never an error on the kiosk.
"""
from __future__ import annotations

import logging
import threading
import time

from app.spacebring_client import get_spacebring_client, spacebring_enabled

logger = logging.getLogger("spacebring.images")

CACHE_SECONDS = 300
_lock = threading.Lock()
_cache: dict[str, str] = {}
_loaded_at = 0.0


def get_room_cover_urls(now: float | None = None) -> dict[str, str]:
    """{spacebring resource id: public cover photo URL}; empty when unavailable."""
    global _cache, _loaded_at
    if not spacebring_enabled():
        return {}
    now = time.monotonic() if now is None else now
    with _lock:
        if _loaded_at and now - _loaded_at < CACHE_SECONDS:
            return _cache
        try:
            rooms = get_spacebring_client().list_rooms()
            _cache = {
                room["id"]: room["media"][0]["url"]
                for room in rooms
                if room.get("media") and room["media"][0].get("url")
            }
        except Exception as exc:  # keep serving the last good answer
            logger.warning("Could not load Spacebring room photos: %s", exc)
        _loaded_at = now
        return _cache
