from google import genai
from app.config import settings

# Create a single client instance (reused)
_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """
    Transcribe audio using Gemini's audio modality via google-genai SDK.
    """
    client = _get_client()
    prompt = "Transcribe the following audio exactly as spoken, with no extra text."
    # Use Part.from_bytes from the types module
    from google.genai.types import Part
    audio_part = Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[prompt, audio_part]
    )
    return response.text