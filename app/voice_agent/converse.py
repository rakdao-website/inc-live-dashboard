from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import base64
from google import genai
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

    # 2. Ensure we have either audio or text
    if not request.audio and not request.message:
        raise HTTPException(status_code=400, detail="Either 'audio' or 'message' must be provided")

    # 3. If not registered, try to extract from the first audio
    if not session.get("registered"):
        if not request.audio:
            # User sent text only but not registered – ask for voice
            reply_text = "Please say your name, email, and whether you're an existing customer."
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
                "registered": False,
            }

        # Decode audio
        try:
            audio_bytes = base64.b64decode(request.audio)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid audio base64")

        # Transcribe the audio
        try:
            # ✅ FIXED: Call transcribe_audio with only audio_bytes and mime_type
            transcript = await transcribe_audio(audio_bytes, request.mime_type)
            log_info(f"Transcript: {transcript}")
        except Exception as e:
            log_error(f"Transcription failed: {e}")
            reply_text = "I couldn't understand the audio. Please say your name, email, and if you're an existing customer."
            # ✅ Generate TTS and return error response
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
                "registered": False,
                "error": "transcription_failed",
            }

        # Extract using your robust function
        parsed: ParsedVisitor = await parse_visitor_intent(transcript)
        if parsed.full_name and parsed.email and parsed.visitor_type:
            phone = parsed.mobile_number
            # Store the extracted info
            update_session(
                request.session_id,
                name=parsed.full_name,
                email=parsed.email,
                phone=phone,
                existing_customer=(parsed.visitor_type == "client")
            )
            reply_text = (
                f"Thank you, {parsed.full_name}. I have your email as {parsed.email}. "
                f"and phone as {phone if phone else ' not provided '}. "
                f"You are {'an existing' if parsed.visitor_type == 'client' else 'a new'} customer. "
                "How can I help you today?"
            )
        else:
            # Ask for missing fields
            missing = parsed.missing
            reply_text = "I didn't catch all the details. "
            if "full_name" in missing:
                reply_text += "Please say your full name. "
            if "email" in missing:
                reply_text += "Please say your email address."
            if "visitor_type" in missing:
                reply_text += "And tell me if you are an existing customer."
            # We don't register yet; will retry on next audio

        # Generate TTS for this response
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
            "extracted": parsed.to_dict() if parsed else None,
        }

    # 4. Normal conversation (registered)
    parts = []
    if request.message:
        parts.append(request.message)
    if request.audio:
        audio_bytes = base64.b64decode(request.audio)
        parts.append(genai.types.Part.from_bytes(audio_bytes, mime_type=request.mime_type))

    reply_text, err = await get_gemini_response(request.session_id, parts)
    if err:
        raise HTTPException(status_code=500, detail=err)

    try:
        audio_bytes, content_type = await synthesize_speech(reply_text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except TtsUnavailable:
        audio_b64 = None
        content_type = None

    ended = False
    if "goodbye" in reply_text.lower():
        clear_session(request.session_id)
        ended = True

    return {
        "session_id": request.session_id,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "session_ended": ended,
        "registered": True,
    }

@router.post("/register")
async def register_voice(request: RegisterRequest):
    # 1. Create session if not provided
    if not request.session_id:
        request.session_id = str(uuid.uuid4())
        create_session(request.session_id)
        log_info(f"New session created: {request.session_id}")

    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired session")

    # 2. Decode and transcribe
    if not request.audio:
        raise HTTPException(status_code=400, detail="Audio required")
    try:
        audio_bytes = base64.b64decode(request.audio)
    except:
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
        return {
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
            "registered": False,
        }

    # 3. Extract using your robust parser
    parsed = await parse_visitor_intent(transcript)
    if parsed.full_name and parsed.email and parsed.mobile_number and parsed.visitor_type:
        # Store all fields in session
        update_session(
            request.session_id,
            name=parsed.full_name,
            email=parsed.email,
            phone=parsed.mobile_number,
            existing_customer=(parsed.visitor_type == "client")
        )
        reply_text = (
            f"Thank you, {parsed.full_name}. I have your email as {parsed.email} "
            f"and phone as {parsed.mobile_number}. "
            f"You are {'an existing' if parsed.visitor_type == 'client' else 'a new'} customer. "
            "You are now registered. How can I help you today?"
        )
    else:
        # Ask for missing fields
        missing = parsed.missing
        reply_text = "I didn't catch all the details. "
        if "full_name" in missing:
            reply_text += "Please say your full name. "
        if "email" in missing:
            reply_text += "Please say your email address. "
        if "mobile_number" in missing:
            reply_text += "Please say your phone number. "
        reply_text += "And tell me if you are an existing customer."

    # 4. Generate TTS for the reply
    try:
        audio_bytes, content_type = await synthesize_speech(reply_text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except TtsUnavailable:
        audio_b64 = None

    return {
        "session_id": request.session_id,
        "extracted": parsed.to_dict() if parsed else None,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "registered": session.get("registered", False),
    }


@router.post("/login")
async def login_voice(request: LoginRequest):
    # 1. Create session if not provided
    if not request.session_id:
        request.session_id = str(uuid.uuid4())
        create_session(request.session_id)
        log_info(f"New session created: {request.session_id}")

    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired session")

    # 2. Decode and transcribe
    if not request.audio:
        raise HTTPException(status_code=400, detail="Audio required")
    try:
        audio_bytes = base64.b64decode(request.audio)
    except:
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
        return {
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
        }

    # 3. Extract using the same parser (we only need name and phone)
    parsed = await parse_visitor_intent(transcript)
    if parsed.full_name and parsed.mobile_number:
        # Store minimal info in session (optional)
        update_session(
            request.session_id,
            name=parsed.full_name,
            phone=parsed.mobile_number,
            # Don't set email or existing_customer because we don't have them
        )
        reply_text = f"Welcome back, {parsed.full_name}. I have your phone number as {parsed.mobile_number}. How can I help you?"
    else:
        missing = parsed.missing
        reply_text = "I didn't catch all the details. "
        if "full_name" in missing:
            reply_text += "Please say your full name. "
        if "mobile_number" in missing:
            reply_text += "Please say your phone number. "

    # 4. Generate TTS
    try:
        audio_bytes, content_type = await synthesize_speech(reply_text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except TtsUnavailable:
        audio_b64 = None

    return {
        "session_id": request.session_id,
        "extracted": {
            "full_name": parsed.full_name,
            "mobile_number": parsed.mobile_number,
        } if parsed.full_name and parsed.mobile_number else None,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "logged_in": bool(parsed.full_name and parsed.mobile_number),
    }

@router.post("/booking")
async def booking(request: BookingRequest):
    # 1. Validate session
    if not request.session_id:
        request.session_id = str(uuid.uuid4())
        create_session(request.session_id, visitor_id=request.visitor_id)
        log_info(f"New session created: {request.session_id}")
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired session")
    if session.get("visitor_id") != request.visitor_id:
        session["visitor_id"] = request.visitor_id

    # 2. Decode and transcribe
    if not request.audio:
        raise HTTPException(status_code=400, detail="Audio required")
    try:
        audio_bytes = base64.b64decode(request.audio)
    except:
        raise HTTPException(status_code=400, detail="Invalid audio base64")
    try:
        transcript = await transcribe_audio(audio_bytes, request.mime_type)
        log_info(f"Booking transcript: {transcript}")
    except Exception as e:
        log_error(f"Transcription failed: {e}")
        reply_text = "I couldn't understand the audio. Please try again."
        try:
            audio_bytes, content_type = await synthesize_speech(reply_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except TtsUnavailable:
            audio_b64 = None
        return {
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
        }

    # 3. Parse booking using your existing parser
    try:
        with SessionLocal() as db:
            parsed = await parse_booking_intent(db, transcript, request.service_type)
        booking_data = parsed.to_dict()
    except Exception as e:
        log_error(f"Booking parsing failed: {e}")
        reply_text = "I couldn't understand your booking details. Please try again."
        try:
            audio_bytes, content_type = await synthesize_speech(reply_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except TtsUnavailable:
            audio_b64 = None
        return {
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
        }

    # 4. Check for missing fields
    if parsed.missing:
        missing_labels = []
        if "room" in parsed.missing:
            missing_labels.append("the room name")
        if "date" in parsed.missing:
            missing_labels.append("the date")
        if "time" in parsed.missing:
            missing_labels.append("the time")
        if "duration" in parsed.missing:
            missing_labels.append("the duration")
        reply_text = f"I need {', '.join(missing_labels)}. Please say them clearly."
        try:
            audio_bytes, content_type = await synthesize_speech(reply_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except TtsUnavailable:
            audio_b64 = None
        return {
            "session_id": request.session_id,
            "booking_details": booking_data,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
        }

    # 5. Call internal booking API
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://localhost:8000/api/kiosk/bookings",
                json={
                    "visitor_id": request.visitor_id,
                    "service_type": request.service_type,
                    "zone_id": booking_data["zone_id"],
                    "booking_date": booking_data["booking_date"],
                    "booking_time_start": booking_data["booking_time_start"],
                    "duration_minutes": int(booking_data["duration_minutes"]),
                }
            )
            if resp.status_code != 200:
                error_detail = resp.json().get("detail", "Booking failed")
                raise Exception(error_detail)
            booking_result = resp.json()
    except Exception as e:
        reply_text = f"Booking failed: {str(e)}"
        try:
            audio_bytes, content_type = await synthesize_speech(reply_text)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        except TtsUnavailable:
            audio_b64 = None
        return {
            "session_id": request.session_id,
            "booking_details": booking_data,
            "reply_text": reply_text,
            "reply_audio": audio_b64,
        }

    # 6. Success TTS
    reply_text = (
        f"Booking confirmed for {booking_data['zone_name'] or booking_data['zone_id']} "
        f"on {booking_data['booking_date']} at {booking_data['booking_time_start']} "
        f"for {booking_data['duration_minutes']} minutes."
    )
    try:
        audio_bytes, content_type = await synthesize_speech(reply_text)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except TtsUnavailable:
        audio_b64 = None

    return {
        "session_id": request.session_id,
        "booking_details": booking_data,
        "booking_result": booking_result,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
    }