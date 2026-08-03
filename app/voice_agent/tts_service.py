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

_SAMPLE_RATE_RE = re.compile(r"rate=(\d+)")


class TtsUnavailable(RuntimeError):
    """Raised when TTS is disabled, unconfigured, or the provider call fails."""


def _pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm_data), b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", len(pcm_data),
    )
    return header + pcm_data


async def _synthesize_gemini(text: str) -> tuple[bytes, str]:
    if not settings.gemini_api_key:
        raise TtsUnavailable("GEMINI_API_KEY is not configured on the server.")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_tts_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.gemini_tts_voice}}
            },
        },
    }

    async with httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=body)

    if response.status_code != 200:
        raise TtsUnavailable(f"Gemini TTS request failed with status {response.status_code}: {response.text}")

    data = response.json()
    try:
        part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
        audio_b64 = part["data"]
        mime_type = part.get("mimeType", "")
    except (KeyError, IndexError) as exc:
        raise TtsUnavailable(f"Gemini TTS returned an unexpected response shape: {data}") from exc

    pcm_bytes = base64.b64decode(audio_b64)

    rate_match = _SAMPLE_RATE_RE.search(mime_type)
    if not rate_match:
        raise TtsUnavailable(f"Could not determine sample rate from Gemini response mimeType: {mime_type!r}")
    sample_rate = int(rate_match.group(1))

    return _pcm_to_wav(pcm_bytes, sample_rate=sample_rate), "audio/wav"


async def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type) - WAV for Gemini."""
    if not settings.tts_enabled:
        raise TtsUnavailable("Server-side text-to-speech is not enabled.")

    if settings.tts_provider == "gemini":
        return await _synthesize_gemini(text)

    raise TtsUnavailable(
        f"Unrecognized tts_provider {settings.tts_provider!r} - only 'gemini' is currently "
        "supported by this file. Set TTS_PROVIDER=gemini in .env, or reintroduce the xAI "
        "branch if that provider is still needed."
    )