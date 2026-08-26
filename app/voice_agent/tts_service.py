"""
Server-side text-to-speech. Provider is chosen via settings.tts_provider:
"openrouter" (routes to whatever model/voice is configured there) or "xai"
(calls api.x.ai directly). Kept server-side so API keys never reach the
browser - the frontend calls our /api/kiosk/speak endpoint instead of the
provider directly, and falls back to the browser's own speechSynthesis
automatically if this is disabled, misconfigured, or the request fails for
any reason.

xAI's /v1/audio/speech returns a ready-to-play MP3 directly in the response
body.

OpenRouter's behavior depends on the underlying model: most return MP3
directly, but routing to a Gemini model returns raw PCM audio samples,
base64-encoded, with no file header at all. That's not something a browser
<audio> element can play as-is; a proper WAV header has to be built around
it first, using the sample rate Gemini reports (24kHz). Getting the sample
rate wrong produces audio that "plays" but at the wrong pitch/speed.
"""

import asyncio
import base64
import json
import re
import struct

import httpx
import websockets

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

async def _post_with_retries(url: str, payload: dict, headers: dict, provider_label: str) -> httpx.Response:
    """POST with a short automatic retry on transient network failures
    (timeouts, dropped connections) - these tend to succeed on a quick
    second try, same as manually retrying from the UI."""
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
                f"{provider_label} TTS request failed after {TTS_MAX_ATTEMPTS} attempts: {exc}"
            ) from exc

    if response is None:
        # Should be unreachable (the loop above either returns a response or
        # raises), but keeps type-checkers and future refactors honest.
        raise TtsUnavailable(f"{provider_label} TTS request failed: {last_network_error}")
    return response


def _raise_for_error_response(response: httpx.Response, provider_label: str) -> None:
    if response.status_code == 200:
        return
    try:
        error_data = response.json()
        error_msg = error_data.get("error", {}).get("message", response.text)
    except Exception:
        error_msg = response.text
    raise TtsUnavailable(f"{provider_label} TTS failed: {response.status_code} - {error_msg}")


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

    response = await _post_with_retries(url, payload, headers, "OpenRouter")
    _raise_for_error_response(response, "OpenRouter")

    content = response.content

    if response_format == "pcm":
        # Gemini returns PCM raw audio; convert to WAV
        wav_bytes = _pcm_to_wav(content, sample_rate=24000)  # Gemini uses 24kHz
        return wav_bytes, "audio/wav"

    return content, "audio/mpeg"


async def _synthesize_xai(text: str) -> tuple[bytes, str]:
    """xAI's real-time TTS is a WebSocket protocol (wss://api.x.ai/v1/tts),
    not a plain HTTP endpoint: you send `text.delta` / `text.done`, and get
    `audio.delta` chunks back (base64-encoded) followed by `audio.done`.

    This buffers every chunk and returns one complete clip - same shape as
    the OpenRouter path - so nothing else in the app (converse.py, the
    frontend) needs to change. NOTE: buffering the full response this way
    does NOT reduce latency versus a plain HTTP call - the model still has
    to generate the whole clip before we return it. The actual latency win
    of this protocol only materializes if audio is streamed all the way to
    the browser as it arrives, which needs converse.py and the frontend
    playback to both become streaming-aware - a separate, bigger change.
    """
    if not settings.xai_api_key:
        raise TtsUnavailable("XAI_API_KEY is not configured")

    uri = (
        f"wss://api.x.ai/v1/tts?language={settings.xai_tts_language}"
        f"&voice={settings.xai_tts_voice}&codec={settings.xai_tts_codec}"
    )
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}

    last_error: Exception | None = None
    for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
        audio_bytes = bytearray()
        try:
            async with websockets.connect(
                uri,
                additional_headers=headers,
                open_timeout=TTS_TIMEOUT_SECONDS,
            ) as ws:
                await ws.send(json.dumps({"type": "text.delta", "delta": text}))
                await ws.send(json.dumps({"type": "text.done"}))

                async for raw_msg in ws:
                    event = json.loads(raw_msg)
                    event_type = event.get("type")
                    if event_type == "audio.delta":
                        audio_bytes.extend(base64.b64decode(event["delta"]))
                    elif event_type == "audio.done":
                        break
                    elif event_type == "error":
                        # An application-level error from xAI (bad voice
                        # name, etc.) - retrying won't fix this, fail now.
                        raise TtsUnavailable(f"xAI TTS error: {event.get('message', 'unknown error')}")

            if not audio_bytes:
                raise TtsUnavailable("xAI TTS returned no audio")

            content_type = "audio/mpeg" if settings.xai_tts_codec == "mp3" else f"audio/{settings.xai_tts_codec}"
            return bytes(audio_bytes), content_type

        except TtsUnavailable:
            raise
        except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as exc:
            # Transient connection-level failure - worth a quick retry,
            # same as the HTTP providers.
            last_error = exc
            if attempt < TTS_MAX_ATTEMPTS:
                await asyncio.sleep(TTS_RETRY_DELAY_SECONDS)
                continue
            raise TtsUnavailable(
                f"xAI TTS WebSocket failed after {TTS_MAX_ATTEMPTS} attempts: {exc}"
            ) from exc

    raise TtsUnavailable(f"xAI TTS WebSocket failed: {last_error}")


# Reuses one open WebSocket connection per conversation session instead of
# opening a fresh one on every single reply - xAI's TTS protocol explicitly
# supports multiple text.delta/text.done "turns" over one persistent
# connection, so paying a new TLS+WebSocket handshake every reply was pure
# unnecessary latency. Keyed by our own /converse session_id.
_xai_tts_connections: dict[str, "websockets.WebSocketClientProtocol"] = {}


def _xai_tts_uri() -> str:
    return (
        f"wss://api.x.ai/v1/tts?language={settings.xai_tts_language}"
        f"&voice={settings.xai_tts_voice}&codec={settings.xai_tts_codec}"
    )


async def _open_xai_tts_connection():
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    return await websockets.connect(_xai_tts_uri(), additional_headers=headers, open_timeout=TTS_TIMEOUT_SECONDS)


async def _get_xai_tts_connection(session_id: str | None):
    """Reuse a cached connection for this session if it's still open;
    otherwise open a fresh one (and cache it, if we have a session_id to
    key it by)."""
    if session_id:
        ws = _xai_tts_connections.get(session_id)
        if ws is not None:
            try:
                if not ws.closed:
                    return ws
            except Exception:
                pass
            _xai_tts_connections.pop(session_id, None)

    ws = await _open_xai_tts_connection()
    if session_id:
        _xai_tts_connections[session_id] = ws
    return ws


async def close_xai_tts_session(session_id: str) -> None:
    """Call this once a conversation is actually over (visitor handed off
    after login/registration/booking, session reset, etc.) to release its
    cached connection instead of leaving it open until it eventually times
    out on its own. Safe to call even if there's nothing cached."""
    ws = _xai_tts_connections.pop(session_id, None)
    if ws is not None:
        try:
            await ws.close()
        except Exception:
            pass


async def stream_synthesize_xai(text_chunks, session_id: str | None = None):
    """
    Real-time streaming TTS: accepts an async iterator of text chunks (e.g.
    from conversation_agent.stream_next_response) and yields raw audio byte
    chunks as xAI generates them - this is what actually lets playback start
    before the full reply (or the full audio clip) exists, unlike
    _synthesize_xai above which buffers everything before returning.

    Pass session_id to reuse one connection across the whole conversation
    (recommended - see _get_xai_tts_connection above). Without it, a fresh
    connection is opened and closed every call, same as before.

    Runs two things concurrently:
      - a sender task forwarding each incoming text chunk as `text.delta`,
        sending `text.done` once the input iterator is exhausted
      - the main loop here, forwarding each `audio.delta` chunk out as raw
        bytes, stopping once `audio.done` arrives

    No automatic retry here (unlike the buffered version) - once partial
    audio has already been yielded to the caller (and likely already
    started playing), silently restarting from scratch isn't meaningful;
    failures propagate so the caller can decide how to handle a partial
    utterance. A connection that fails is evicted from the cache so the
    next turn opens a fresh one rather than reusing a broken one.

    Callers know the content type ahead of time from settings.xai_tts_codec
    (e.g. "mp3" -> "audio/mpeg") since it's fixed for the whole stream.
    """
    if not settings.xai_api_key:
        raise TtsUnavailable("XAI_API_KEY is not configured")

    ws = await _get_xai_tts_connection(session_id)

    async def evict_and_close():
        if session_id:
            _xai_tts_connections.pop(session_id, None)
        try:
            await ws.close()
        except Exception:
            pass

    try:
        async def sender():
            async for chunk in text_chunks:
                if chunk:
                    await ws.send(json.dumps({"type": "text.delta", "delta": chunk}))
            await ws.send(json.dumps({"type": "text.done"}))

        sender_task = asyncio.create_task(sender())
        try:
            async for raw_msg in ws:
                event = json.loads(raw_msg)
                event_type = event.get("type")
                if event_type == "audio.delta":
                    yield base64.b64decode(event["delta"])
                elif event_type == "audio.done":
                    break
                elif event_type == "error":
                    raise TtsUnavailable(f"xAI TTS error: {event.get('message', 'unknown error')}")
            # Success - leave the connection open (cached) for the next turn.
        finally:
            if not sender_task.done():
                sender_task.cancel()
                try:
                    await sender_task
                except (asyncio.CancelledError, Exception):
                    pass
            elif sender_task.exception():
                raise TtsUnavailable(f"xAI TTS send failed: {sender_task.exception()}")

    except TtsUnavailable:
        await evict_and_close()
        raise
    except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as exc:
        await evict_and_close()
        raise TtsUnavailable(f"xAI TTS WebSocket failed: {exc}") from exc


async def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type) - WAV for Gemini, MP3 otherwise."""
    if not settings.tts_enabled:
        raise TtsUnavailable("Server-side text-to-speech is not enabled.")

    if settings.tts_provider == "openrouter":
        return await _synthesize_openrouter(text)
    if settings.tts_provider == "xai":
        return await _synthesize_xai(text)

    raise TtsUnavailable(
        f"Unrecognized tts_provider {settings.tts_provider!r} - only 'openrouter' and 'xai' are "
        "currently supported by this file. Set TTS_PROVIDER to one of those in .env."
    )