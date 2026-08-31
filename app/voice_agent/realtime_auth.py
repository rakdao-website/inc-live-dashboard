"""
Mints short-lived ("ephemeral") credentials for OpenAI's Realtime API.

The actual voice session (RealtimeSession/RealtimeAgent, via
@openai/agents/realtime) runs entirely client-side in the browser over
WebSocket - the browser needs a credential to connect directly to OpenAI,
but it must never see the real OPENAI_API_KEY. This endpoint calls OpenAI
server-side to mint a short-lived client_secret and hands only that back
to the frontend.

NOTE ON THE REQUEST BODY BELOW: OpenAI's docs referenced for this project
confirm the endpoint is POST https://api.openai.com/v1/realtime/client_secrets,
but didn't specify the exact request/response body shape. This sends a
minimal, reasonable body (session type/model/voice) based on the general
pattern of OpenAI's realtime session config - if this 400s, check the
actual request body OpenAI expects in their current API reference and
adjust the `payload` dict below; the response is assumed to contain a
"client_secret" object with a "value" field (or similar) which is
extracted defensively below.
"""

import httpx
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.voice_agent.knowledge_base_loader import load_knowledge_base as _load_knowledge_base
from app.voice_agent.utils.logger import log_error, log_info

router = APIRouter()

OPENAI_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
REQUEST_TIMEOUT_SECONDS = 10

_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)


@router.get("/knowledge-base")
async def get_knowledge_base():
    """
    Serves the same knowledge_base.md content the text pipeline uses,
    for the realtime agent (which runs client-side and can't read the
    file off the server's disk directly) to fetch once at connect time
    and fold into its instructions. Reuses the existing cached loader -
    editing knowledge_base.md still takes effect immediately, no restart
    needed, same as the text pipeline.
    """
    return {"knowledge_base": _load_knowledge_base()}


@router.post("/realtime-session")
async def create_realtime_session():
    """
    Returns a short-lived client secret the frontend can use to connect
    directly to OpenAI's Realtime API via WebSocket. Call this once per
    conversation (when the visitor opens the realtime voice assistant).
    """
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    # Minimal session config - the frontend's RealtimeAgent/RealtimeSession
    # config (instructions, tools, turn detection, etc.) still applies once
    # connected; this just establishes the model/voice for the token itself.
    payload = {
        "session": {
            "type": "realtime",
            "model": settings.openai_realtime_model,
            "audio": {
                "output": {"voice": settings.openai_realtime_voice},
            },
        }
    }

    try:
        response = await _client.post(OPENAI_CLIENT_SECRETS_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        log_error(f"Failed to reach OpenAI to mint realtime client secret: {exc}")
        raise HTTPException(status_code=502, detail="Could not reach OpenAI") from exc

    if response.status_code != 200:
        log_error(f"OpenAI client_secrets request failed: {response.status_code} - {response.text}")
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI rejected the client_secret request: {response.status_code} - {response.text}",
        )

    data = response.json()
    log_info(f"Minted realtime client secret (response keys: {list(data.keys())})")

    # Defensive extraction - the exact response shape wasn't confirmed, so
    # this tries the most likely places for the token before giving up.
    client_secret = None
    if isinstance(data.get("client_secret"), dict):
        client_secret = data["client_secret"].get("value")
    elif isinstance(data.get("client_secret"), str):
        client_secret = data["client_secret"]
    elif isinstance(data.get("value"), str):
        client_secret = data["value"]

    if not client_secret:
        log_error(f"Could not find client_secret in OpenAI response: {data!r}")
        raise HTTPException(
            status_code=502,
            detail="Unexpected response shape from OpenAI - check realtime_auth.py against current API docs",
        )

    return {
        "client_secret": client_secret,
        "model": settings.openai_realtime_model,
        "raw": data,  # included for debugging while verifying the response shape; remove once confirmed
    }