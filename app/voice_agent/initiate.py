from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
from app.voice_agent.utils.validator import validate_initiate
from app.voice_agent.session_manager import create_session
from app.voice_agent.utils.logger import log_info

router = APIRouter()

class InitiateRequest(BaseModel):
    name: str
    email: str
    existingCustomer: bool

@router.post("/initiate")
async def initiate(request: InitiateRequest):
    error = validate_initiate(request.dict())
    if error:
        raise HTTPException(status_code=400, detail=error)

    session_id = str(uuid.uuid4())
    create_session(
        session_id,
        request.name,
        request.email,
        request.existingCustomer
    )
    log_info(f"Session initiated: {session_id}")
    return {
        "session_id": session_id,
        "message": "Voice agent session created. Send audio or text via /converse."
    }