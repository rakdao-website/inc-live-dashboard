import httpx
import json
import asyncio
from app.config import settings
from app.voice_agent.utils.logger import log_info, log_error

XAI_BASE_URL = "https://api.x.ai/v1"
MAX_RETRIES = 2
BASE_DELAY = 1  # seconds
REQUEST_TIMEOUT_SECONDS = 12
MAX_REPLY_TOKENS = 400  # Replies are a short JSON object with a sentence or
                          # two of speech - this just bounds worst-case
                          # generation time, it shouldn't ever be hit normally.

# Reused across every call instead of opening a fresh connection (and doing
# a new TLS handshake) each time.
_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)


async def call_xai(prompt: str, system: str = None, temperature: float = 0.3) -> str:
    """
    Call xAI's Chat Completions API directly (not via OpenRouter), with
    retries. Same interface as call_openrouter, so it's a drop-in swap.
    Returns the text response.
    """
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY is not set in environment")
 
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
 
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }
 
    payload = {
        "model": settings.xai_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": MAX_REPLY_TOKENS,
    }
 
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await _client.post(
                f"{XAI_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
 
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                log_info(f"xAI response (attempt {attempt}): {content[:100]}...")
                return content
 
            error_msg = f"xAI returned status {response.status_code}: {response.text}"
            log_error(error_msg)
 
            if response.status_code in (429, 500, 502, 503, 504):
                delay = BASE_DELAY * (2 ** (attempt - 1))
                log_info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                continue
 
            raise Exception(f"xAI API error: {error_msg}")
 
        except httpx.TimeoutException:
            log_error(f"xAI request timed out (attempt {attempt})")
            if attempt == MAX_RETRIES:
                raise TimeoutError("xAI request timed out after multiple attempts")
            await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))
 
        except Exception as e:
            log_error(f"xAI request failed (attempt {attempt}): {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))
 
    raise RuntimeError("xAI request failed after all retries")

async def stream_chat_completion(prompt: str, system: str = None, temperature: float = 0.3):
    """
    Stream a chat completion from xAI, yielding text deltas as they arrive.
    xAI's chat completions endpoint is OpenAI-compatible, same SSE format
    as OpenRouter's: lines of `data: {...}`, terminated by `data: [DONE]`.
    """
    if not settings.xai_api_key:
        raise ValueError("XAI_API_KEY is not set in environment")
 
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
 
    headers = {
        "Authorization": f"Bearer {settings.xai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.xai_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": MAX_REPLY_TOKENS,
        "stream": True,
    }
 
    async with _client.stream(
        "POST", f"{XAI_BASE_URL}/chat/completions", headers=headers, json=payload
    ) as response:
        if response.status_code != 200:
            error_text = await response.aread()
            raise Exception(
                f"xAI streaming request failed: {response.status_code} - "
                f"{error_text.decode(errors='replace')}"
            )
 
        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            content = choices[0].get("delta", {}).get("content")
            if content:
                yield content

