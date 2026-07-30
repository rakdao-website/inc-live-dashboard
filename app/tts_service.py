"""
Server-side text-to-speech via the xAI TTS API. Kept server-side so the
xAI key never reaches the browser - the frontend calls our /api/kiosk/speak
endpoint instead of api.x.ai directly, and falls back to the browser's own
speechSynthesis automatically if this is disabled, misconfigured, or the
request fails for any reason.
"""

import httpx

from app.config import settings

XAI_TTS_URL = "https://api.x.ai/v1/tts"
TTS_TIMEOUT_SECONDS = 15


class TtsUnavailable(RuntimeError):
    """Raised when TTS is disabled, unconfigured, or the provider call fails."""


async def synthesize_speech(text: str) -> bytes:
    if not settings.tts_enabled:
        raise TtsUnavailable("Server-side text-to-speech is not enabled.")
    if not settings.xai_api_key:
        raise TtsUnavailable("XAI_API_KEY is not configured on the server.")

    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "text": text,
        "voice_id": settings.xai_tts_voice,
        "language": "en",
    }

    async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
        response = await client.post(XAI_TTS_URL, headers=headers, json=body)

    if response.status_code != 200:
        raise TtsUnavailable(f"xAI TTS request failed with status {response.status_code}: {response.text}")

    return response.content