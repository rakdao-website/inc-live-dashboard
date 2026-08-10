import re
from datetime import date,datetime,time as time_type

import httpx
import dateparser
from dateparser.search import search_dates
from sqlalchemy.orm import Session

from app.config import settings
from app.kiosk_flow_services import service_to_booking_defaults
from app.room_question_service import build_room_directory,find_room_in_question

LLM_TIMEOUT_SECONDS = 10

# Ordered longest-phrase-first so "an hour and a half" matches before "an hour" does.
_DURATION_PHRASES: list[tuple[str, int]] = [
    ("hour and a half", 90),
    ("an hour and a half", 90),
    ("ninety minutes", 90),
    ("half an hour", 30),
    ("half hour", 30),
    ("two hours", 120),
    ("one hour", 60),
    ("an hour", 60),
    ("thirty minutes", 30),
    ("sixty minutes", 60),
]
_DURATION_NUMBER_RE = re.compile(r"(\d+)\s*(minute|min|hour|hr)s?\b", re.IGNORECASE)

class ParsedBooking:
    def __init__(self):
        self.zone_id: str | None = None
        self.zone_name: str | None = None
        self.booking_date: date | None = None
        self.booking_time_start: time_type | None = None
        self.duration_minutes: int | None = None
        self.date_time_source: str = "none"
        self.missing:list[str] = []

    def to_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "booking_date": self.booking_date.isoformat() if self.booking_date else None,
            "booking_time_start": self.booking_time_start.isoformat() if self.booking_time_start else None,
            "duration_minutes": self.duration_minutes,
            "date_time_source": self.date_time_source,
            "missing": self.missing,
        }

def _parse_duration(transcript:str) -> int | None:
    t=transcript.lower()
    # Check for known phrases first
    for phrase, minutes in _DURATION_PHRASES:
        if phrase in t:
            return minutes

    # Check for numeric durations
    match = _DURATION_NUMBER_RE.search(t)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        return amount *60 if unit.startswith("h") else amount
    return None

_TIME_WITH_AT_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
# No "at" required, but must look unambiguously like a time (am/pm or :mm) -
# a bare 1-2 digit number alone is NOT enough, since that's indistinguishable
# from a room number ("Meeting Room 1", "Office 5") and matching it caused a
# real regression: it grabbed "1" from "Meeting Room 1" as the time before
# ever reaching the actual "at 10am" later in the sentence.
_TIME_LOOSE_RE = re.compile(r"\b(\d{1,2})(?::(\d{2})|(?=\s*(?:am|pm)\b))\s*(am|pm)?\b", re.IGNORECASE)

def _strip_duration_phrases(transcript:str) -> str:
    t=transcript.lower()
    for phrase, _ in sorted(_DURATION_PHRASES,key=lambda x: -len(x[0])):
        t= re.sub(re.escape(phrase), "", t, flags=re.IGNORECASE)
    t=_DURATION_NUMBER_RE.sub("",t)
    return t

def _parse_date_time_rule_based(transcript: str):
    """ Two passes, not one - dateparser's combined search unreliably drops
        the time (or miscalculates the date) when a relative weekday and a clock
        time appear together in one string. Extracting the time first via regex,
        then searching the remainder for the date, sidesteps that.
    """
    parse_settings = {"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()}
    without_duration = _strip_duration_phrases(transcript)
    time_match = _TIME_WITH_AT_RE.search(without_duration) or _TIME_LOOSE_RE.search(without_duration)
    parsed_time: time_type | None = None
    remainder = without_duration
    if time_match:
        time_str = time_match.group(0)
        if time_str.lower().startswith("at "):
            time_str = time_str[3:].strip()
        parsed = dateparser.parse(time_str, settings=parse_settings)
        if parsed:
            candidate = parsed.time().replace(second=0, microsecond=0)
            # A bare, ambiguous time like "at 3" (no am/pm) can silently
            # default to midnight - treat that as unparsed, not a real answer.
            parsed_time = None if candidate == time_type(0, 0) else candidate
    if time_match:
        remainder = without_duration[: time_match.start()] + without_duration[time_match.end() :]
    else:
        remainder = without_duration

    date_results = search_dates(remainder, settings=parse_settings)
    parsed_date = date_results[0][1].date() if date_results else None
    return parsed_date, parsed_time
 
 
async def _parse_date_time_llm(transcript: str) -> tuple[date | None, time_type | None]:
    prompt = (
    "Extract a date and time from this sentence, if present. Today is "
    f"{datetime.now().date().isoformat()}. Respond with ONLY a JSON object, no "
    'other text: {"date": "YYYY-MM-DD" or null, "time": "HH:MM" (24-hour) or '
    f'null}}.\n\nSentence: {transcript}')

    raw = None
    try:
        if settings.room_question_provider == "gemini" and settings.gemini_api_key:
            raw = await _call_gemini(prompt)
        elif settings.room_question_provider == "grok" and settings.xai_api_key:
            raw = await _call_grok(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"Booking date/time LLM fallback failed: {exc}")
        return None, None
 
    if not raw:
        return None, None
 
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        import json
        data = json.loads(cleaned)
        parsed_date = date.fromisoformat(data["date"]) if data.get("date") else None
        parsed_time = time_type.fromisoformat(data["time"]) if data.get("time") else None
        return parsed_date, parsed_time
    except Exception as exc:  # noqa: BLE001
        print(f"Booking date/time LLM response unparsable: {exc}")
        return None, None

async def _call_gemini(prompt: str) -> str:
    url = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=body)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
 
 
async def _call_grok(prompt: str) -> str:
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    body = {"model": settings.xai_model, "messages": [{"role": "user", "content": prompt}]}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post("https://api.x.ai/v1/chat/completions", json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

async def parse_booking_intent(db: Session, transcript: str, service_type: str | None = None):
    result = ParsedBooking()
 
    rooms = build_room_directory(db)
    matched_room = find_room_in_question(transcript, rooms)
    if matched_room:
        result.zone_id = matched_room["zone_id"]
        result.zone_name = matched_room["zone_name"]
    elif service_type in {"podcast_studio", "tiktok_studio"}:
        # These services have exactly one physical room, so it's safe to
        # default without asking. Meeting rooms are NOT included here -
        # there are two of them, so if the visitor didn't name one, we
        # should ask which they want rather than silently picking Room 1.
        _, default_zone_id, default_room_name = service_to_booking_defaults(service_type)
        result.zone_id = default_zone_id
        result.zone_name = default_room_name
    else:
        result.missing.append("room")
 
    result.duration_minutes = _parse_duration(transcript)
    if result.duration_minutes is None:
        result.missing.append("duration")
 
    parsed_date, parsed_time = _parse_date_time_rule_based(transcript)
    if parsed_date or parsed_time:
        result.date_time_source = "dateparser"
    else:
        parsed_date, parsed_time = await _parse_date_time_llm(transcript)
        if parsed_date or parsed_time:
            result.date_time_source = "llm"
 
    result.booking_date = parsed_date
    result.booking_time_start = parsed_time
    if not parsed_date:
        result.missing.append("date")
    if not parsed_time:
        result.missing.append("time")
 
    return result