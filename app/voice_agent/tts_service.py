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

import asyncio
import base64
import re
import struct

import httpx

from app.config import settings
import struct
import wave
import io

TTS_TIMEOUT_SECONDS = 15
# Transient network hiccups (timeouts, dropped connections) to the TTS
# provider tend to succeed on a quick second try, same as manually retrying
# from the UI - so retry once, briefly, before giving up and letting the
# caller fall back to text-only / browser speech synthesis.
TTS_MAX_ATTEMPTS = 2
TTS_RETRY_DELAY_SECONDS = 0.75

# Reused across every call instead of opening a fresh connection (and doing
# a new TLS handshake) each time - same host as the LLM calls, so this also
# benefits from connection keep-alive.
_client = httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS)

class TtsUnavailable(RuntimeError):
    """Raised when TTS is disabled, unconfigured, or the provider call fails."""


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Convert raw PCM data to WAV format."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm_data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        len(pcm_data),
    )
    return header + pcm_data

async def _synthesize_openrouter(text: str) -> tuple[bytes, str]:
    if not settings.openrouter_api_key:
        raise TtsUnavailable("OPENROUTER_API_KEY is not configured")

    url = "https://openrouter.ai/api/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    
    # Determine response_format based on model
    model = settings.openrouter_tts_model
    if "gemini" in model.lower():
        response_format = "pcm"  # Gemini requires PCM
    else:
        response_format = "mp3"  # Others support MP3

    payload = {
        "model": model,
        "input": text,
        "voice": settings.openrouter_tts_voice,
        "response_format": response_format,
    }

    response = None
    last_network_error: Exception | None = None
    for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
        try:
            response = await _client.post(url, json=payload, headers=headers)
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_network_error = exc
            if attempt < TTS_MAX_ATTEMPTS:
                await asyncio.sleep(TTS_RETRY_DELAY_SECONDS)
                continue
            raise TtsUnavailable(
                f"OpenRouter TTS request failed after {TTS_MAX_ATTEMPTS} attempts: {exc}"
            ) from exc

    if response is None:
        # Should be unreachable (the loop above either returns a response or
        # raises), but keeps type-checkers and future refactors honest.
        raise TtsUnavailable(f"OpenRouter TTS request failed: {last_network_error}")

    if response.status_code != 200:
        try:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", response.text)
        except:
            error_msg = response.text
        raise TtsUnavailable(f"OpenRouter TTS failed: {response.status_code} - {error_msg}")

    content = response.content

    if response_format == "pcm":
        # Gemini returns PCM raw audio; convert to WAV
        wav_bytes = _pcm_to_wav(content, sample_rate=24000)  # Gemini uses 24kHz
        return wav_bytes, "audio/wav"

    return content, "audio/mpeg"


async def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type) - WAV for Gemini."""
    if not settings.tts_enabled:
        raise TtsUnavailable("Server-side text-to-speech is not enabled.")

    if settings.tts_provider == "openrouter":
        return await _synthesize_openrouter(text)

    raise TtsUnavailable(
        f"Unrecognized tts_provider {settings.tts_provider!r} - only 'openrouter' is currently "
        "supported by this file. Set TTS_PROVIDER=openrouter in .env, or reintroduce the xAI "
        "branch if that provider is still needed."
    )