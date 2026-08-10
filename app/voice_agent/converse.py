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
import re





router = APIRouter()

class ConverseRequest(BaseModel):
    session_id: str = None
    audio: str = None
    message: str = None
    mime_type: str = "audio/wav"
    # Set by the frontend once a visitor is already logged in/registered
    # (e.g. reopening the assistant on a booking or other page), so the
    # agent doesn't repeat the greeting/login/registration questions.
    visitor_id: int = None
    visitor_name: str = None
    visitor_type: str = None
    # Which booking page the visitor is on, if any (meeting_room /
    # podcast_studio / tiktok_studio) - lets booking intent default the
    # room when they don't name one explicitly.
    service_type: str = None

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

    # 1b. If the frontend already knows who this visitor is (e.g. the voice
    # assistant was reopened on a different page after they already logged
    # in / registered), mark the session registered right away so the agent
    # skips straight to Q&A instead of re-running the greeting/login flow.
    if request.visitor_id and not session.get("registered"):
        session.setdefault("collected", {})
        session["visitor_id"] = request.visitor_id
        session["registered"] = True
        if request.visitor_name:
            session["name"] = request.visitor_name
            session["collected"]["name"] = request.visitor_name
        if request.visitor_type:
            session["visitor_type"] = request.visitor_type
            session["collected"]["visitor_type"] = request.visitor_type

    if request.service_type:
        session["service_type"] = request.service_type

    # Snapshot registration state *after* the pre-authentication shortcut
    # above but *before* this turn's login/register handling runs. This is
    # what lets us tell "was already registered coming into this turn"
    # (an already-known visitor greeted on a new page) apart from "this
    # turn is the one that just completed login/registration" - only the
    # latter should tell the frontend to wrap up and hand off.
    was_registered_before_this_turn = session.get("registered", False)

    # 2. Transcribe audio if provided
    transcript = None
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
            # Generate TTS for error
            try:
                audio_bytes, content_type = await synthesize_speech(reply_text)
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            except TtsUnavailable:
                audio_b64 = None
                content_type = None
            return {
                "session_id": request.session_id,
                "reply_text": reply_text,
                "reply_audio": audio_b64,
                "audio_content_type": content_type,
                "session_ended": False,
                "registered": session.get("registered", False),
                "just_registered": False,
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
        return {
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
            "audio_content_type": content_type,
            "session_ended": False,
            "registered": session.get("registered", False),
            "just_registered": False,
            "extracted": None,
            "step": "waiting_input",
        }

    # 3. Get LLM response
    llm_data = await get_next_response(transcript, session)
    extracted = llm_data.get("extracted", {})
    session.setdefault("collected", {})
    for key, value in extracted.items():
        if value and key in ["name", "email", "phone", "visitor_type"]:
            session[key] = value
            session["collected"][key] = value

    missing = llm_data.get("missing", [])
    session["missing"] = missing

    action = llm_data.get("action", "retry")
    reply_text = llm_data.get("reply", "Processing...")

    # 4. Handle login/register if not already registered
    # Login only needs a name + phone to look someone up. Registration also
    # only needs name + phone - email is a nice-to-have (used if it was
    # already picked up during the greeting) but never blocks either flow.
    if action in ("login", "register") and not session.get("registered"):
        required_fields = ["name", "phone"]
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
                        # Continue to registration block below (fall through)

                if action == "register":
                    # Try to create new visitor. Email is optional here -
                    # use whatever's already been collected (may be None).
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            "http://localhost:8000/api/kiosk/profiles",
                            json={
                                "full_name": session["name"],
                                "email": session.get("email"),
                                "mobile_number": phone_normalized,
                                "visitor_type": session.get("visitor_type", "visitor"),
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
            reply_text = f"I still need your {' and '.join(missing_fields)} to continue."

    # 4b. Handle booking intent for already-registered visitors. This spans
    # multiple turns (room/date/time/duration can arrive across several
    # messages), so we accumulate into session["booking"] and only ask for
    # whatever's still missing, rather than restarting each time.
    if session.get("registered"):
        cancelling = session.get("booking_active") and re.search(
            r"\b(cancel|never mind|forget it|nevermind)\b", transcript, re.IGNORECASE
        )
        if cancelling:
            session["booking_active"] = False
            session["booking"] = {}
            reply_text = "No problem - just let me know if you'd like to book something else."
        elif action == "booking_intent" or session.get("booking_active"):
            session["booking_active"] = True
            booking = session.setdefault("booking", {})
            try:
                with SessionLocal() as db:
                    parsed = await parse_booking_intent(db, transcript, service_type=session.get("service_type"))
                for key in ("zone_id", "zone_name", "booking_date", "booking_time_start", "duration_minutes"):
                    value = getattr(parsed, key, None)
                    if not value:
                        continue
                    if key == "booking_time_start":
                        booking[key] = value.strftime("%H:%M")
                    elif hasattr(value, "isoformat"):
                        booking[key] = value.isoformat()
                    else:
                        booking[key] = value
            except Exception as e:
                log_error(f"Booking intent parse error: {e}")

            still_missing = []
            if not booking.get("zone_id"):
                still_missing.append("which room")
            if not booking.get("booking_date"):
                still_missing.append("what date")
            if not booking.get("booking_time_start"):
                still_missing.append("what time")
            if not booking.get("duration_minutes"):
                still_missing.append("how long you need it")

            if still_missing:
                reply_text = f"Got it. Could you also tell me {', '.join(still_missing)}?"
            else:
                session["booking_active"] = False
                session["booking_ready"] = True
                room_label = booking.get("zone_name") or booking.get("zone_id")
                reply_text = (
                    f"Great - {room_label} on {booking['booking_date']} at {booking['booking_time_start']} "
                    f"for {booking['duration_minutes']} minutes. Let's confirm those details now."
                )

    # 5. Generate TTS for the reply
    try:
        audio_bytes, content_type = await synthesize_speech(reply_text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except TtsUnavailable:
        audio_b64 = None
        content_type = None

    # 6. Return response
    booking_ready_now = session.get("booking_ready", False)
    if booking_ready_now:
        # One-shot signal - the frontend hands off to the manual booking
        # form to confirm, so don't keep repeating this once it's been sent.
        session["booking_ready"] = False

    just_registered_now = session.get("registered", False) and not was_registered_before_this_turn

    return {
        "session_id": request.session_id,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "session_ended": False,
        "registered": session.get("registered", False),
        "just_registered": just_registered_now,
        "booking_ready": booking_ready_now,
        "extracted": {
            **{k: session[k] for k in ["name", "email", "phone", "visitor_type"] if session.get(k)},
            **session.get("booking", {}),
        },
        "step": action,
    }