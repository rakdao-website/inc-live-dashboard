import httpx
import json
from app.config import settings
import asyncio
from app.voice_agent.utils.logger import log_info, log_error


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = settings.openrouter_api_key
OPENROUTER_MODEL = settings.openrouter_model  # e.g., "google/gemini-2.5-flash"
MAX_RETRIES = 3
BASE_DELAY = 1  # seconds

async def call_openrouter(prompt: str, system: str = None, temperature: float = 0.3) -> str:
    """
    Call OpenRouter Chat Completions API with retries.
    Returns the text response.
    """
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in environment")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": temperature,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    log_info(f"OpenRouter response (attempt {attempt}): {content[:100]}...")
                    return content

                # Non‑200 response
                error_msg = f"OpenRouter returned status {response.status_code}: {response.text}"
                log_error(error_msg)

                # If we're rate‑limited or server error, retry
                if response.status_code in (429, 500, 502, 503, 504):
                    delay = BASE_DELAY * (2 ** (attempt - 1))
                    log_info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    continue

                # Other errors (e.g., 400) are unlikely to resolve with retry
                raise Exception(f"OpenRouter API error: {error_msg}")

        except httpx.TimeoutException:
            log_error(f"OpenRouter request timed out (attempt {attempt})")
            if attempt == MAX_RETRIES:
                raise TimeoutError("OpenRouter request timed out after multiple attempts")
            await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))

        except Exception as e:
            log_error(f"OpenRouter request failed (attempt {attempt}): {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))

    raise RuntimeError("OpenRouter request failed after all retries")
