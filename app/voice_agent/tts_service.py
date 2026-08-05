"""
Server-side text-to-speech, xAI or Gemini depending on settings.tts_provider.
Kept server-side so the API key never reaches the browser - the frontend
calls our /api/kiosk/speak endpoint instead of the provider directly, and
falls back to the browser's own speechSynthesis automatically if this is
disabled, misconfigured, or the request fails for any reason.

xAI's /v1/tts returns a ready-to-play MP3 directly.

Gemini's generateContent (audio modality) does NOT - it returns raw PCM
audio samples, base64-encoded, with no file header at all. That's not
something a browser <audio> element can play as-is; a proper WAV header has
to be built around it first, using the sample rate Gemini reports in the
response's mimeType (e.g. "audio/L16;codec=pcm;rate=24000"). Getting the
sample rate wrong produces audio that "plays" but at the wrong pitch/speed,
so it's parsed from the actual response rather than assumed constant.
"""

import base64
import re
import struct

import httpx

from app.config import settings


TTS_TIMEOUT_SECONDS = 15

class TtsUnavailable(RuntimeError):
    """Raised when TTS is disabled, unconfigured, or the provider call fails."""

async def _synthesize_openroute(text: str):
    if not settings.openrouter_api_key:
        raise TtsUnavailable("OPENROUTER_API_KEY is not configured on the server.")

    url = "https://openrouter.ai/api/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.openrouter_tts_model,
        "input": text,
        "voice": settings.openrouter_tts_voice,
        "response_format": "mp3",  # or "wav" – MP3 works well with browsers
    }

    async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        raise TtsUnavailable(
            f"OpenRouter TTS failed with status {response.status_code}: {response.text}"
        )

    return response.content, "audio/mpeg"

async def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type) - WAV for Gemini."""
    if not settings.tts_enabled:
        raise TtsUnavailable("Server-side text-to-speech is not enabled.")

    if settings.tts_provider == "openrouter":
        return await _synthesize_openroute(text)

    raise TtsUnavailable(
        f"Unrecognized tts_provider {settings.tts_provider!r} - only 'openrouter' is currently "
        "supported by this file. Set TTS_PROVIDER=openrouter in .env, or reintroduce the xAI "
        "branch if that provider is still needed."
    )