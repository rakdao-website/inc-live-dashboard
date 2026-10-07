"""
Automatic Arabic translation for kiosk text that changes (event names and
locations from the database, messages written by the backend).

The kiosk's fixed screen text is translated in advance in the frontend
(components/kiosk/i18n.tsx). Anything not in that file is sent here:

  1. Already translated before?  -> returned from the translation_cache
     table instantly (no AI call, no cost).
  2. New text?                   -> translated by Gemini in one batch,
     using the same settings as room_question_service.py, then saved.
  3. Gemini unavailable / fails? -> nothing is returned for that text, and
     the kiosk simply keeps showing the English. Nothing breaks.
"""

import hashlib
import json
import re

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TranslationCache

LLM_TIMEOUT_SECONDS = 15
MAX_TEXTS_PER_REQUEST = 50
MAX_TEXT_LENGTH = 1000

# Same tone and conventions as the hand-written Arabic in the frontend, so
# automatic translations don't stand out.
_PROMPT = """You translate short texts shown on a visitor kiosk at Innovation City, a free zone \
in Ras Al Khaimah, UAE, from English into Arabic.

Rules:
- Clear, polite Modern Standard Arabic as used by UAE government and business services. \
Natural phrasing, not word-for-word.
- "Innovation City" is "مدينة الابتكار"; "free zone" is "المنطقة الحرة".
- Keep people's names and company/brand names recognisable (transliterate only well-known \
brands as Arabic readers know them, e.g. TikTok -> تيك توك).
- Use Western digits (0-9). Write times as e.g. "2:00 مساءً" / "9:30 صباحاً".
- Keep any {placeholders} exactly as they are.
- Return ONLY a JSON object that maps each original text, exactly as given, to its Arabic \
translation. No comments, no markdown.

Texts:
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _needs_translation(text: str) -> bool:
    """Skip empty text, numbers/codes, emails, and text already in Arabic."""
    if not text or len(text) > MAX_TEXT_LENGTH:
        return False
    if re.search(r"[\u0600-\u06FF]", text):
        return False
    if "@" in text and " " not in text:
        return False
    return bool(re.search(r"[A-Za-z]{2,}", text))


async def _ask_gemini(texts: list[str]) -> dict[str, str]:
    api_key = getattr(settings, "gemini_api_key", None)
    model = getattr(settings, "gemini_model", None)
    if not api_key or not model:
        return {}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": _PROMPT + json.dumps(texts, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=body)
    response.raise_for_status()
    raw = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    result = json.loads(raw)
    # Keep only clean answers for texts we actually asked about.
    return {
        source: translated.strip()
        for source, translated in result.items()
        if source in texts and isinstance(translated, str) and translated.strip()
    }


async def translate_texts(db: Session, texts: list[str], target_lang: str = "ar") -> dict[str, str]:
    """Returns {english: arabic} for every text that could be translated."""
    unique = list(dict.fromkeys(t for t in texts[:MAX_TEXTS_PER_REQUEST] if _needs_translation(t)))
    if not unique:
        return {}

    hashes = {_hash(text): text for text in unique}
    cached_rows = (
        db.query(TranslationCache)
        .filter(TranslationCache.target_lang == target_lang, TranslationCache.source_hash.in_(list(hashes)))
        .all()
    )
    translations = {hashes[row.source_hash]: row.translated_text for row in cached_rows}

    missing = [text for text in unique if text not in translations]
    if missing:
        try:
            fresh = await _ask_gemini(missing)
        except Exception as exc:  # noqa: BLE001 - any failure: keep English
            print(f"Kiosk translation failed, showing English instead: {exc}")
            fresh = {}
        for source, translated in fresh.items():
            db.add(
                TranslationCache(
                    source_hash=_hash(source),
                    source_text=source,
                    target_lang=target_lang,
                    translated_text=translated,
                )
            )
            translations[source] = translated
        if fresh:
            try:
                db.commit()
            except Exception:  # noqa: BLE001 - e.g. two kiosks saved the same text at once
                db.rollback()

    return translations
