"""
Room Q&A for the kiosk voice assistant.

Live status (available/occupied/closed) always comes from the real `zones`
table via zones_with_status() - never fabricated. Descriptive details
(capacity, floor, features) are NOT in the database (Zone only has
zone_id/zone_name/zone_type/is_bookable/is_closed), so they're supplied here
in ROOM_DETAILS instead. Fill in your real numbers - anything left out just
falls back to an honest, generic answer based on the room's real zone_type,
rather than a made-up specific.
"""

import re

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.services import zones_with_status

LLM_TIMEOUT_SECONDS = 12

# ---------------------------------------------------------------------------
# Shared defaults by zone_type - applied to every room of that type unless
# overridden below in ROOM_DETAILS for a specific zone_id. Use this for
# things true of most rooms of a kind (e.g. all offices have the same base
# furniture); use ROOM_DETAILS for anything specific to one room.
ROOM_TYPE_DEFAULTS: dict[str, dict] = {
    "office": {
        "features": [
            "4 work tables and chairs",
            "Movable drawer with a key, with storage underneath",
            "Shared table for storage",
        ],
        "description": (
            "Offices are on the Ground Floor and the 5th Floor. Each office is "
            "leased to a different company, so furnishings can vary slightly by room - "
            "ask the tenant company or front desk for specifics on a particular office."
        ),
    },
}

# Fill this in with your real rooms' real details. Keyed by zone_id (matches
# the Zone table, e.g. "MR_1", "POD_1", "TTS_1" - see seed.py for your IDs).
# "aliases" are extra phrases visitors might use that don't literally contain
# the zone_name, to catch natural phrasing beyond an exact-name match.
# Every field is optional; omit what you don't want stated. Anything set here
# overrides the type-level default above for that specific room.
ROOM_DETAILS: dict[str, dict] = {
    "MR_1": {
        "capacity": "6-7",
        "features": ["Large table", "TV screen"],
        "description": "Used for meetings.",
    },
    "MR_2": {
        "capacity": "6-7",
        "features": ["Large table", "TV screen"],
        "description": "Used for meetings.",
    },
    "POD_1": {
        "floor": "Ground Floor",
        "description": (
            "A studio where Innovation City customers can record podcasts for free, "
            "for a limited number of hours."
        ),
        "aliases": ["podcast room", "recording studio"],
    },
    "TTS_1": {
        "floor": "Ground Floor",
        "description": (
            "An exciting collaboration where customers will be able to create TikTok "
            "content and ads for free, for a limited number of hours."
        ),
        "aliases": ["tik tok studio", "tik tok room", "content studio"],
        # Not open yet - see _describe_room, this suppresses the live
        # available/occupied line so it doesn't contradict "coming soon".
        "coming_soon": True,
    },
    # VERIFY "BC_1" against your real zones table (SELECT zone_id, zone_name
    # FROM zones WHERE zone_name ILIKE '%business%') - if the id doesn't
    # match, this entry silently matches nothing. Update the key if needed.
    "BC_1": {
        "floor": "Ground Floor",
        "description": (
            "A space where founders and companies can showcase their products and "
            "demos. Also used as a networking space."
        ),
        "aliases": ["business area", "showcase area", "demo space"],
        "always_include": True,
    },
}

_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, and convert spelled-out small numbers
    to digits so "meeting room one" matches "Meeting Room 1"."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()
    words = [_NUMBER_WORDS.get(w, w) for w in words]
    return " ".join(words)


def _zone_type_label(zone_type: str) -> str:
    return zone_type.replace("_", " ")


def build_room_directory(db: Session) -> list[dict]:
    """A 'room' a visitor can ask about is either bookable (a meeting room,
    studio, office) or explicitly marked always_include in ROOM_DETAILS for
    informational spaces that aren't reserved like a meeting room (e.g. a
    walk-in showcase/networking area). Either way, a closed zone is excluded."""
    zones = zones_with_status(db)
    rooms = []
    for z in zones:
        specific = ROOM_DETAILS.get(z["zone_id"], {})
        if z["is_closed"]:
            continue
        if not z["is_bookable"] and not specific.get("always_include"):
            continue
        type_defaults = ROOM_TYPE_DEFAULTS.get(z["zone_type"], {})
        z["details"] = {**type_defaults, **specific}
        rooms.append(z)
    return rooms


def _match_terms(room: dict) -> list[str]:
    terms = [room["zone_name"].lower()]
    terms.extend(alias.lower() for alias in room["details"].get("aliases", []))
    return terms


def find_room_in_question(question: str, rooms: list[dict]) -> dict | None:
    normalized_question = _normalize(question)
    for room in rooms:
        for term in _match_terms(room):
            if _normalize(term) in normalized_question:
                return room
    return None


def _describe_room(room: dict) -> str:
    """Full description: type, floor, capacity, features, description, and
    live status - not just status alone."""
    details = room["details"]
    parts = [f"{room['zone_name']} is a {_zone_type_label(room['zone_type'])}"]

    extra = []
    if details.get("floor"):
        extra.append(f"on {details['floor']}")
    if details.get("capacity"):
        extra.append(f"seats {details['capacity']}")
    if extra:
        parts[0] += " " + ", ".join(extra)
    parts[0] += "."

    if details.get("features"):
        parts.append("Features: " + ", ".join(details["features"]) + ".")
    if details.get("description"):
        parts.append(details["description"])

    if details.get("coming_soon"):
        parts.append("This isn't open yet - it's coming soon.")
    else:
        parts.append(f"It's currently {room['status']}.")
    return " ".join(parts)


def _directory_text(rooms: list[dict]) -> str:
    if not rooms:
        return "No bookable rooms are currently configured."
    lines = []
    for r in rooms:
        d = r["details"]
        bits = [f"{r['zone_name']} ({_zone_type_label(r['zone_type'])})"]
        if d.get("coming_soon"):
            bits.append("status: coming soon, not open yet")
        else:
            bits.append(f"status: {r['status']}")
        if d.get("floor"):
            bits.append(f"floor: {d['floor']}")
        if d.get("capacity"):
            bits.append(f"capacity: {d['capacity']}")
        if d.get("features"):
            bits.append("features: " + ", ".join(d["features"]))
        line = ", ".join(bits)
        if d.get("description"):
            line += f". {d['description']}"
        lines.append(line)
    return "\n".join(lines)


def scripted_answer(question: str, rooms: list[dict]) -> str:
    q = _normalize(question)
    if not q:
        return "Could you say that again? I didn't catch a question."

    room = find_room_in_question(question, rooms)
    if room:
        return _describe_room(room)

    if "available" in q:
        available = [
            r["zone_name"] for r in rooms
            if r["status"] == "available" and not r["details"].get("coming_soon")
        ]
        if not available:
            return "No rooms are available right now."
        return "Available right now: " + ", ".join(available) + "."

    if "list" in q or "what rooms" in q or "which rooms" in q:
        if not rooms:
            return "There are no bookable rooms configured right now."
        return "We have: " + ", ".join(r["zone_name"] for r in rooms) + "."

    return "I didn't catch a room name. Try asking, for example, tell me about the Podcast Studio."


def _prompt(question: str, rooms: list[dict]) -> str:
    return (
        "You are a front-desk room directory assistant. Using ONLY this room "
        "list, answer the visitor's question - which may ask about anything "
        "(capacity, features, floor, availability, general description), not "
        "just whether a room is free - in 1-3 short sentences. If nothing "
        f"matches, say so.\n\nRooms:\n{_directory_text(rooms)}\n\nQuestion: {question}"
        "make your answer concise, friendly, and conversational, with no markdown, lists."
    )


async def _ask_gemini(question: str, rooms: list[dict]) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = {"contents": [{"parts": [{"text": _prompt(question, rooms)}]}]}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=body)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _ask_grok(question: str, rooms: list[dict]) -> str:
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    body = {
        "model": settings.xai_model,
        "messages": [{"role": "user", "content": _prompt(question, rooms)}],
    }
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            "https://api.x.ai/v1/chat/completions", json=body, headers=headers
        )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


async def answer_room_question(db: Session, question: str) -> tuple[str, str]:
    """Returns (answer, source) where source is 'llm' or 'scripted'."""
    rooms = build_room_directory(db)

    try:
        if settings.room_question_provider == "gemini" and settings.gemini_api_key:
            return await _ask_gemini(question, rooms), "llm"
        if settings.room_question_provider == "grok" and settings.xai_api_key:
            return await _ask_grok(question, rooms), "llm"
    except Exception as exc:  # noqa: BLE001 - any provider failure falls back
        print(f"Room-question LLM call failed, falling back to scripted matcher: {exc}")

    return scripted_answer(question, rooms), "scripted"