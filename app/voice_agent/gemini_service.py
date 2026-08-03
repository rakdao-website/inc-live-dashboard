from google import genai
from app.config import settings


client = genai.Client(api_key=settings.gemini_api_key)

async def get_gemini_response(session_id: str, parts: list):
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=parts
    )
    return response.text,None