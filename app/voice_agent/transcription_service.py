from app.config import settings

# services/transcription_service.py
import base64
import httpx
from app.config import settings
from app.voice_agent.utils.logger import log_info, log_error

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
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

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
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

