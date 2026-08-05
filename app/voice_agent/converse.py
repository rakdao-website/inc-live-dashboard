from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import base64
from google import genai
from app.voice_agent.conversation_agent import get_next_response
from app.voice_agent.gemini_service import get_gemini_response
from app.voice_agent.tts_service import synthesize_speech, TtsUnavailable
from app.voice_agent.session_manager import get_session,create_session,update_session,clear_session
from app.voice_agent.utils.logger import log_info, log_error
from app.registration_intent_service import parse_visitor_intent, ParsedVisitor
from app.voice_agent.transcription_service import transcribe_audio
from app.voice_agent.utils.logger import log_info, log_error
from app.booking_intent_service import parse_booking_intent
from app.database import SessionLocal
import uuid
import httpx





router = APIRouter()

class ConverseRequest(BaseModel):
    session_id: str = None
    audio: str = None
    message: str = None
    mime_type: str = "audio/wav"

# Additional models at the top
class RegisterRequest(BaseModel):
    session_id: str = None
    audio: str
    mime_type: str = "audio/wav"

class LoginRequest(BaseModel):
    session_id: str = None
    audio: str
    mime_type: str = "audio/wav"

class BookingRequest(BaseModel):
    session_id: str = None
    audio: str
    mime_type: str = "audio/wav"
    visitor_id: int
    service_type: str = "meeting_room"

def normalize_phone_(phone: str):
    if not phone:
        return phone
    phone = phone.strip()
    if phone.startswith("+"):
        return phone
    # Remove leading zeros
    cleaned = phone.lstrip("0")
    # Assume UAE if no country code
    return f"+971{cleaned}"

from app.database import SessionLocal
from app.models import Visitor

async def find_visitor_by_phone(phone: str) -> dict | None:
    """Find visitor by phone number using direct database query."""
    if not phone:
        return None
    
    # Clean phone: remove non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) < 7:
        return None
    
    with SessionLocal() as db:
        # Try exact match with phone as stored
        visitor = db.query(Visitor).filter(Visitor.visitor_phone == phone).first()
        if visitor:
            return {
                "visitor_id": visitor.visitor_id,
                "visitor_name": visitor.visitor_name,
                "visitor_phone": visitor.visitor_phone,
                "visitor_email": visitor.visitor_email,
                "visitor_type": visitor.visitor_type,
            }
        
        # Try without country code (if phone has +)
        if phone.startswith("+"):
            without_plus = phone[1:]
            visitor = db.query(Visitor).filter(Visitor.visitor_phone == without_plus).first()
            if visitor:
                return visitor_data(visitor)
        
        # Try with country code if phone doesn't have it
        if not phone.startswith("+"):
            with_plus = f"+{phone}"
            visitor = db.query(Visitor).filter(Visitor.visitor_phone == with_plus).first()
            if visitor:
                return visitor_data(visitor)
        
        # Try last 9 digits (in case of format differences)
        if len(digits) >= 9:
            last_9 = digits[-9:]
            visitor = db.query(Visitor).filter(Visitor.visitor_phone.like(f"%{last_9}")).first()
            if visitor:
                return visitor_data(visitor)
        
        # Try searching by name (if provided) but we only have phone here, so skip.
    
    return None

def visitor_data(visitor):
    return {
        "visitor_id": visitor.visitor_id,
        "visitor_name": visitor.visitor_name,
        "visitor_phone": visitor.visitor_phone,
        "visitor_email": visitor.visitor_email,
        "visitor_type": visitor.visitor_type,
    }
@router.post("/converse")
async def converse(request: ConverseRequest):
    # 1. If no session_id, create one
    if not request.session_id:
        request.session_id = str(uuid.uuid4())
        create_session(request.session_id)
        log_info(f"New session created: {request.session_id}")

    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired session")

    #transcribe audio if provided
    if request.audio:
        try:
            audio_bytes = base64.b64decode(request.audio)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid audio base64")
        try:
            transcript = await transcribe_audio(audio_bytes, request.mime_type)
            log_info(f"Transcript: {transcript}")
        except Exception as e:
            log_error(f"Transcription failed: {e}")
            reply_text = "I couldn't understand the audio. Please try again."
            try:
                audio_bytes, content_type = await synthesize_speech(reply_text)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            except TtsUnavailable:
                audio_b64 = None
                content_type = None
            return{"session_id": request.session_id,
                "reply_text": reply_text,
                "reply_audio": audio_b64,
                "audio_content_type": content_type,
                "session_ended": False,
                "registered": session.get("registered", False),
                "extracted": None,
                "step": "error",
            }

    elif request.message:
        transcript = request.message

    if not transcript:
        reply_text = "I didn't hear anything. Please try again."
        try:
            audio_bytes, content_type = await synthesize_speech(reply_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except TtsUnavailable:
            audio_b64 = None
            content_type = None
        return {"session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
            "audio_content_type": content_type,
            "session_ended": False,
            "registered": session.get("registered", False),
            "extracted": None,
            "step": "waiting_input"}

    llm_data = await get_next_response(transcript, session)
    extracted = llm_data.get("extracted", {})
    for key, value in extracted.items():
        if value and key  in ["name", "email", "phone", "visitor_type"]:
            session[key] = value
            session["collected"][key] = value

    missing = llm_data.get("missing", [])
    session["missing"] = missing

    action = llm_data.get("action", "retry")
    reply_text = llm_data.get("reply", "processing...")

    if action in ("login", "register") and not session.get("registered"):
        required_fields = ["name", "email", "phone", "visitor_type"]
        if all(session.get(field) for field in required_fields):
            phone_normalized = normalize_phone_(session["phone"])
            visitor = None

            try:
                if action == "login":
                # Try profile lookup via API
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                        "http://localhost:8000/api/kiosk/profile-lookup",
                        json={
                            "full_name": session["name"],
                            "mobile_number": phone_normalized,
                        }
                    )
                        if resp.status_code == 200:
                            visitor = resp.json().get("data")
                        else:
                        # Fallback to direct DB search by phone
                            visitor = await find_visitor_by_phone(phone_normalized)

                    if visitor:
                        session["visitor_id"] = visitor["visitor_id"]
                        session["registered"] = True
                        reply_text = f"Welcome back, {visitor['visitor_name']}! You are logged in. How can I help you today?"
                    else:
                    # Not found – fallback to registration
                        reply_text = "I couldn't find your profile. Let's try registering you instead."
                        action = "register"
                    # Continue to registration (fall through)

                if action == "register":
                # Try to create new visitor
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                        "http://localhost:8000/api/kiosk/profiles",
                        json={
                            "full_name": session["name"],
                            "email": session["email"],
                            "mobile_number": phone_normalized,
                            "visitor_type": session["visitor_type"],
                        }
                    )
                        if resp.status_code == 201:
                            visitor = resp.json().get("data")
                            session["visitor_id"] = visitor["visitor_id"]
                            session["registered"] = True
                            reply_text = f"Thank you, {session['name']}! You are registered. How can I help you today?"
                        elif resp.status_code == 409:
                        # Conflict – try to find existing visitor by phone
                            visitor = await find_visitor_by_phone(phone_normalized)
                            if visitor:
                                session["visitor_id"] = visitor["visitor_id"]
                                session["registered"] = True
                                reply_text = f"Welcome back, {visitor['visitor_name']}! You are logged in. How can I help you today?"
                            else:
                                reply_text = "A profile with this phone number already exists, but I couldn't log you in. Please try again."
                        else:
                            reply_text = "Registration failed. Please try again later."
            except Exception as e:
                log_error(f"Registration/login error: {e}")
                reply_text = "I had trouble processing that. Please try again."
        else:
            missing_fields = [field for field in required_fields if not session.get(field)]
            reply_text = f"I still need: {', '.join(missing_fields)}. Could you provide them?"
    # If login or register, call internal APIs (only if not already registered)
            try:
                audio_bytes, content_type = await synthesize_speech(reply_text)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            except TtsUnavailable:
                audio_b64 = None
                content_type = None

    # 8. Return response
        return {
        "session_id": request.session_id,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "session_ended": False,
        "registered": session.get("registered", False),
        "extracted": {k: session[k] for k in ["name", "email", "phone", "visitor_type"] if session.get(k)},
        "step": action,
    }

