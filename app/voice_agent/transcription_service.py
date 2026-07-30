# services/transcription_service.py (new file)

from google import genai
from app.voice_agent.session_manager import get_session
from app.config import settings

# Initialize client once, perhaps in a central location
client = genai.Client(api_key=settings.gemini_api_key)

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    prompt = "Transcribe the following audio exactly as spoken..."
    audio_part = genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[prompt, audio_part]
    )
    return response.text
