from app.config import settings

# services/transcription_service.py
import base64
import httpx
from app.config import settings
from app.voice_agent.utils.logger import log_info, log_error

# Reused across calls instead of opening a fresh connection each time.
_client = httpx.AsyncClient(timeout=30)


def _extension_for_mime(mime_type: str) -> str:
    mapping = {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
        "audio/m4a": "m4a",
        "audio/mp4": "m4a",
    }
    return mapping.get((mime_type or "").lower(), "wav")


async def _transcribe_openrouter(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """
    Transcribe audio using OpenRouter's /audio/transcriptions endpoint.
    Supports WAV, MP3, WebM, etc.
    """
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    # Encode audio to base64
    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    # Determine format from mime_type
    fmt = mime_type.split('/')[-1]  # wav, mp3, webm

    payload = {
        "model": settings.openrouter_stt_model,  # e.g., "openai/whisper-1" or "xai/grok-2-stt"
        "input_audio": {
            "data": audio_b64,
            "format": fmt
        }
    }

    response = await _client.post(
        "https://openrouter.ai/api/v1/audio/transcriptions",
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json=payload
    )

    if response.status_code != 200:
        log_error(f"OpenRouter STT failed: {response.text}")
        raise Exception(f"STT failed: {response.status_code}")

    result = response.json()
    transcript = result.get("text", "").strip()
    log_info(f"Transcribed: {transcript[:80]}...")
    return transcript


async def _transcribe_xai(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """
    Transcribe audio using xAI's /v1/stt endpoint. Unlike OpenRouter's
    JSON+base64 shape above, this is a plain multipart file upload -
    no base64 encoding needed, the raw bytes go straight in the request.
    """
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY is not set")

    ext = _extension_for_mime(mime_type)
    files = {"file": (f"audio.{ext}", audio_bytes, mime_type or "audio/wav")}
    data = {
        "format": "true",
        "language": settings.xai_stt_language,
    }
    if settings.xai_stt_keyterm:
        data["keyterm"] = settings.xai_stt_keyterm

    response = await _client.post(
        "https://api.x.ai/v1/stt",
        headers={"Authorization": f"Bearer {settings.xai_api_key}"},
        files=files,
        data=data,
    )

    if response.status_code != 200:
        log_error(f"xAI STT failed: {response.text}")
        raise Exception(f"STT failed: {response.status_code}")

    result = response.json()
    transcript = (result.get("text") or "").strip()
    log_info(f"Transcribed ({result.get('duration', '?')}s): {transcript[:80]}...")
    return transcript


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """Returns the transcript text for the given audio bytes. Provider is
    chosen via settings.stt_provider: "openrouter" (default) or "xai"."""
    if settings.stt_provider == "xai":
        return await _transcribe_xai(audio_bytes, mime_type)