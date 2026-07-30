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
import uuid





router = APIRouter()

class ConverseRequest(BaseModel):
    session_id: str = None
    audio: str = None
    message: str = None
    mime_type: str = "audio/wav"

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
            # Store the extracted info
            update_session(
                request.session_id,
                name=parsed.full_name,
                email=parsed.email,
                existing_customer=(parsed.visitor_type == "client")
            )
            reply_text = (
                f"Thank you, {parsed.full_name}. I have your email as {parsed.email}. "
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
