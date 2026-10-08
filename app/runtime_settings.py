"""Settings that staff can change from the admin panel without editing .env or restarting.

Each setting has a typed definition (range or allowed choices). The effective value
is the database override if one exists, otherwise the .env default. Secrets (API keys,
tokens, passwords) are never part of this registry.

Values are cached for a few seconds, so a change reaches every worker almost at once.
"""

from __future__ import annotations

import json
import logging
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import time
from typing import Any, Callable

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base

logger = logging.getLogger("runtime.settings")
CACHE_SECONDS = 5.0


class AppSetting(Base):
    __tablename__ = "app_settings"

    setting_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    setting_value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    updated_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[Any] = mapped_column(DateTime, nullable=False)


@dataclass(frozen=True)
class Definition:
    key: str
    group: str
    label: str
    description: str
    kind: str  # bool | int | float | choice | time
    default: Callable[[], Any]
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    unit: str | None = None
    confirm: str | None = None  # shown in a confirmation dialog before saving
    effect: str = "Applies within a few seconds."
    order: int = 0


GROUP_TITLES = {
    "voice": "Voice agent",
    "face": "Face recognition",
    "scan": "Kiosk face scan",
    "display": "Kiosk display",
    "spacebring": "Spacebring",
    "bookings": "Bookings and events",
}

REALTIME_MODELS = tuple(
    dict.fromkeys([settings.openai_realtime_model, *[m.strip() for m in settings.openai_realtime_model_choices.split(",") if m.strip()]])
)
REALTIME_VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


DEFINITIONS: tuple[Definition, ...] = (
    Definition("voice.realtime_model", "voice", "Realtime voice model", "The OpenAI model the kiosk voice assistant talks to.",
               "choice", lambda: settings.openai_realtime_model, choices=REALTIME_MODELS,
               effect="Applies to the next voice conversation.", confirm="Changing the model changes voice quality and OpenAI cost for new conversations.", order=1),
    Definition("voice.voice", "voice", "Assistant voice", "The voice the assistant speaks with.",
               "choice", lambda: settings.openai_realtime_voice, choices=REALTIME_VOICES,
               effect="Applies to the next voice conversation.", order=2),
    Definition("voice.text_provider", "voice", "Room question answers", "How the kiosk answers room questions and understands typed or spoken requests. Scripted needs no key.",
               "choice", lambda: settings.room_question_provider, choices=("scripted", "gemini", "grok"),
               effect="Applies to the next question. Gemini and Grok fall back to scripted if no key is configured.", order=3),

    Definition("voice.allow_interruptions", "voice", "Let visitors interrupt the assistant", "When on, the assistant stops talking if the visitor keeps speaking over it. Turn it off in a noisy place so it always finishes its sentence.",
               "bool", lambda: True,
               effect="Applies to the next voice conversation.", order=4),
    Definition("voice.interrupt_min_ms", "voice", "Speech needed to interrupt", "How long the visitor must keep speaking before the assistant stops. Coughs, taps and short noises are shorter than this and are ignored.",
               "int", lambda: 700, minimum=200, maximum=2000, unit="ms",
               effect="Applies to the next voice conversation. Only used when interruptions are allowed.", order=5),
    Definition("voice.vad_threshold", "voice", "Microphone sensitivity", "How loud and close speech must be to count. Higher needs louder, closer speech (less pickup of background noise); lower picks up quieter speech.",
               "float", lambda: 0.7, minimum=0.3, maximum=0.95,
               confirm="Too high and quiet speakers may not be heard. Too low and background noise can trigger the assistant.",
               effect="Applies to the next voice conversation.", order=6),
    Definition("voice.silence_ms", "voice", "Pause before it answers", "How long the visitor must stay silent before the assistant treats the turn as finished. Longer is calmer but slower.",
               "int", lambda: 600, minimum=300, maximum=2000, unit="ms",
               effect="Applies to the next voice conversation.", order=7),
    Definition("voice.noise_reduction", "voice", "Noise reduction", "Close mic suits someone standing at the kiosk; far field suits a microphone further away. Off sends the raw microphone sound.",
               "choice", lambda: "near_field", choices=("near_field", "far_field", "off"),
               effect="Applies to the next voice conversation.", order=8),

    Definition("face.match_threshold", "face", "Recognition threshold", "Minimum similarity for the kiosk to say \"Welcome back\". Higher is stricter.",
               "float", lambda: 0.60, minimum=0.45, maximum=0.85,
               confirm="Lowering this makes it more likely the kiosk greets the wrong person as someone else. Raising it makes more known people look unknown.", order=1),
    Definition("face.web_search_enabled", "face", "FaceCheck.ID web search", "Search the public web for look-alikes when a face is not recognised. Uses paid credits unless demo mode is on.",
               "bool", lambda: settings.face_web_search_enabled,
               confirm="Switching this on sends unknown visitors' face images to FaceCheck.ID.", order=2),
    Definition("face.web_search_demo_mode", "face", "FaceCheck.ID demo mode", "Demo mode costs no credits but returns inaccurate results.",
               "bool", lambda: settings.face_web_search_testing_mode,
               confirm="Turning demo mode off makes every search use real credits.", order=3),
    Definition("face.web_search_max_images", "face", "Photos per web search", "How many of the scan photos are sent for one search. Extra photos of the same person do not cost extra credits.",
               "int", lambda: settings.face_web_search_max_images, minimum=1, maximum=5, order=4),

    Definition("scan.duration_ms", "scan", "Scan duration", "How long the scanning ring runs on the kiosk.",
               "int", lambda: 1800, minimum=800, maximum=6000, unit="ms",
               effect="Applies when a kiosk screen next loads.", order=1),
    Definition("scan.recognition_photos", "scan", "Photos for recognition", "Photos taken when checking whether someone is known. More is slower but steadier.",
               "int", lambda: 3, minimum=1, maximum=3, effect="Applies when a kiosk screen next loads.", order=2),
    Definition("scan.enrolment_photos", "scan", "Photos for enrolment", "Photos taken when saving a new person's face.",
               "int", lambda: 3, minimum=1, maximum=5, effect="Applies when a kiosk screen next loads.", order=3),

    Definition("display.stretch_to_screen", "display", "Stretch to fill the screen", "On: the kiosk page is stretched to cover the whole screen edge to edge (for the tall vertical kiosk display). Off: it keeps its 9:16 shape and is centred with bars at the sides (for a laptop or desktop monitor).",
               "bool", lambda: True,
               effect="Applies when a kiosk screen next loads. A kiosk that is already open picks it up after a refresh.", order=1),

    Definition("spacebring.sync_enabled", "spacebring", "Automatic Spacebring sync", "Pull bookings made or changed in Spacebring into the local copy.",
               "bool", lambda: settings.spacebring_sync_interval_seconds > 0,
               effect="Applies at the next sync cycle. Does nothing if Spacebring credentials are not configured.", order=1),
    Definition("spacebring.sync_interval_seconds", "spacebring", "Sync every", "How often the automatic sync runs.",
               "int", lambda: settings.spacebring_sync_interval_seconds or 60, minimum=30, maximum=3600, unit="seconds",
               effect="Applies at the next sync cycle.", order=2),

    Definition("bookings.open_time", "bookings", "Opening time", "Earliest start for bookings and events (24-hour HH:MM, Dubai time).",
               "time", lambda: "09:00", effect="Applies to new bookings and events straight away.", order=1),
    Definition("bookings.close_time", "bookings", "Closing time", "Latest end for bookings and events (24-hour HH:MM, Dubai time).",
               "time", lambda: "17:00", effect="Applies to new bookings and events straight away.", order=2),
)

BY_KEY = {d.key: d for d in DEFINITIONS}


class SettingError(ValueError):
    """The submitted value is not allowed for this setting."""


def validate(definition: Definition, value: Any) -> Any:
    kind = definition.kind
    if kind == "bool":
        if not isinstance(value, bool):
            raise SettingError("Must be true or false.")
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingError("Must be a number.")
        number = int(value) if kind == "int" else float(value)
        if kind == "int" and float(value) != number:
            raise SettingError("Must be a whole number.")
        if definition.minimum is not None and number < definition.minimum:
            raise SettingError(f"Must be at least {definition.minimum:g}.")
        if definition.maximum is not None and number > definition.maximum:
            raise SettingError(f"Must be at most {definition.maximum:g}.")
        return number
    if kind == "choice":
        if value not in definition.choices:
            raise SettingError("Choose one of: " + ", ".join(definition.choices) + ".")
        return value
    if kind == "time":
        try:
            parsed = _hhmm(str(value))
        except (ValueError, TypeError):
            raise SettingError("Use 24-hour HH:MM, for example 09:00.") from None
        return f"{parsed.hour:02d}:{parsed.minute:02d}"
    raise SettingError("Unsupported setting type.")


def validate_combination(values: dict[str, Any]) -> None:
    """Cross-field rules, checked against the full set of effective values."""
    if _hhmm(values["bookings.open_time"]) >= _hhmm(values["bookings.close_time"]):
        raise SettingError("Opening time must be earlier than closing time.")


# --- reading -------------------------------------------------------------

# Replaced in tests. Returns {key: json_text}.
def _load_overrides() -> dict[str, Any]:
    from app.database import SessionLocal

    with SessionLocal() as db:
        return {row.setting_key: json.loads(row.setting_value) for row in db.query(AppSetting).all()}


loader: Callable[[], dict[str, Any]] = _load_overrides
_cache: dict[str, Any] = {}
_cache_at = 0.0
_lock = threading.Lock()


def invalidate() -> None:
    global _cache_at
    with _lock:
        _cache_at = 0.0


def overrides() -> dict[str, Any]:
    global _cache, _cache_at
    now = _time.monotonic()
    with _lock:
        if now - _cache_at < CACHE_SECONDS:
            return _cache
    try:
        fresh = loader()
    except Exception:  # database or table unavailable: keep the last known values
        logger.warning("Could not read app_settings; using the last known values", exc_info=True)
        with _lock:
            _cache_at = now
            return _cache
    with _lock:
        _cache, _cache_at = fresh, now
        return _cache


def get(key: str) -> Any:
    definition = BY_KEY[key]
    value = overrides().get(key)
    if value is None:
        return definition.default()
    try:
        return validate(definition, value)
    except SettingError:
        return definition.default()


def source(key: str) -> str:
    return "database" if key in overrides() else "default"


def operating_hours() -> tuple[time, time]:
    return _hhmm(get("bookings.open_time")), _hhmm(get("bookings.close_time"))


def operating_hours_message() -> str:
    start, end = operating_hours()

    def fmt(value: time) -> str:
        hour = value.hour % 12 or 12
        return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"

    return f"Bookings and events must be scheduled between {fmt(start)} and {fmt(end)}."
