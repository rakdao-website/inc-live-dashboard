from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import base64
import json
from google import genai
from app.voice_agent.conversation_agent import get_next_response, stream_next_response
from app.voice_agent.gemini_service import get_gemini_response
from app.voice_agent.tts_service import synthesize_speech, stream_synthesize_xai, close_xai_tts_session
from app.voice_agent.session_manager import get_session,create_session,update_session,clear_session
from app.voice_agent.utils.logger import log_info, log_error
from app.registration_intent_service import parse_visitor_intent, ParsedVisitor
from app.voice_agent.transcription_service import transcribe_audio
from app.voice_agent.utils.logger import log_info, log_error
from app.booking_intent_service import parse_booking_intent
from app.database import SessionLocal
from app.config import settings
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
def _prepare_session(request: ConverseRequest) -> dict:
    """Session setup shared by both /converse and /converse/stream: resolve
    which session this request belongs to, create it if needed, and apply
    the pre-authentication shortcut for a visitor the frontend already
    knows about.

    Once visitor_id is known, we key the session by the visitor's identity
    ("visitor:<id>") instead of trusting whatever session_id the client
    sent - visitor_id gets resent on every request for an already-known
    visitor regardless of what's happening client-side, so this is what
    actually makes the conversation (booking in progress, collected
    info, etc.) survive even if the client's own session_id tracking ever
    drops or resets. request.session_id is overwritten with the resolved
    id so the rest of this request, and the response sent back to the
    client, stay consistent with whichever session was actually used.
    """
    if request.visitor_id:
        resolved_id = f"visitor:{request.visitor_id}"
    else:
        resolved_id = request.session_id or str(uuid.uuid4())
    request.session_id = resolved_id

    session = get_session(resolved_id)
    if session is None:
        create_session(resolved_id, visitor_id=request.visitor_id)
        session = get_session(resolved_id)
        log_info(f"New session created: {resolved_id}")

    log_info(f"_prepare_session resolved_id={resolved_id!r} session_object_id={id(session)} current_state={session!r}")

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

    return session


async def _extract_transcript(request: ConverseRequest) -> tuple[str | None, str | None, str | None]:
    """Returns (transcript, error_reply, error_step). If error_reply is set,
    the caller should short-circuit with that message instead of calling
    the LLM. Raises HTTPException for a malformed audio payload."""
    if request.audio:
        try:
            audio_bytes = base64.b64decode(request.audio)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid audio base64")
        try:
            transcript = await transcribe_audio(audio_bytes, request.mime_type)
            log_info(f"Transcript: {transcript}")
            return transcript, None, None
        except Exception as e:
            log_error(f"Transcription failed: {e}")
            return None, "I couldn't understand the audio. Please try again.", "error"
    elif request.message:
        return request.message, None, None
    return None, "I didn't hear anything. Please try again.", "waiting_input"


def _merge_extracted_into_session(session: dict, extracted: dict) -> None:
    session.setdefault("collected", {})
    for key, value in (extracted or {}).items():
        if value and key in ["name", "email", "phone", "visitor_type"]:
            session[key] = value
            session["collected"][key] = value
    log_info(f"_merge_extracted_into_session: merged={extracted!r} session_object_id={id(session)} session_id={session.get('visitor_id')!r}")


def _resolve_action(session: dict, action: str) -> str:
    """Cross-checks the LLM's chosen action against what the session
    actually already has, and corrects it if they disagree.

    The model can occasionally lose track mid-conversation - e.g. re-ask
    for name/email/visitor_type via a "collect_*" action even though the
    session already has all of it (visible to it as "Current collected
    info" in its own context, and it should have moved on to
    login/register). Trusting the model's self-reported action blindly
    lets that kind of lapse reach the visitor as a confusing "let's start
    over" reply. If the session already has everything needed to log in
    or register, that takes priority over whatever action the model picked.
    """
    log_info(
        f"_resolve_action check: incoming_action={action!r} registered={session.get('registered')!r} "
        f"name={session.get('name')!r} phone={session.get('phone')!r} "
        f"visitor_type={session.get('visitor_type')!r} session_object_id={id(session)}"
    )
    if not session.get("registered"):
        if session.get("name") and session.get("phone") and session.get("visitor_type"):
            forced = "login" if session["visitor_type"] == "client" else "register"
            if action != forced:
                log_info(f"Correcting LLM action {action!r} -> {forced!r}: session already has name+phone+visitor_type")
                return forced
    return action


def _will_override_reply(session: dict, action: str, transcript: str) -> bool:
    """True if _run_business_logic is going to replace the LLM's own reply
    text with something else for this turn - i.e. NOT safe to stream the
    LLM's raw reply straight into TTS as it's generated."""
    if action in ("login", "register") and not session.get("registered"):
        return True
    if action == "booking_intent" and not session.get("registered"):
        return True
    if session.get("registered"):
        cancelling = session.get("booking_active") and re.search(
            r"\b(cancel|never mind|forget it|nevermind)\b", transcript, re.IGNORECASE
        )
        if cancelling:
            return True
        if action == "booking_intent" or session.get("booking_active"):
            return True
    return False


async def _run_business_logic(session: dict, action: str, transcript: str, reply_text: str) -> tuple[str, str]:
    """Runs login/register/booking_intent side effects, mutating session
    (registered/visitor_id/booking/booking_active/booking_ready) and
    returning the (possibly overridden) reply_text and (possibly
    overridden, e.g. a failed login falling through to register) action."""

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
                            visitor = await find_visitor_by_phone(phone_normalized)

                    if visitor:
                        session["visitor_id"] = visitor["visitor_id"]
                        session["registered"] = True
                        reply_text = f"Welcome back, {visitor['visitor_name']}! You are logged in. How can I help you today?"
                    else:
                        reply_text = "I couldn't find your profile. Let's try registering you instead."
                        action = "register"

                if action == "register":
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

    # A booking_intent before the visitor is signed in has nowhere to go -
    # a booking needs to be attached to a visitor record. Say so plainly
    # instead of leaving the LLM's own "sure, let's get that booked"
    # acknowledgment hanging with no follow-through.
    if action == "booking_intent" and not session.get("registered"):
        reply_text = (
            "I'll need to get you signed in first before I can book anything - could I get your "
            "full name, your email, and whether you're an existing customer or this is your first time?"
        )

    # Booking intent for already-registered visitors. Spans multiple turns
    # (room/date/time/duration can arrive across several messages), so we
    # accumulate into session["booking"] and only ask for whatever's still
    # missing, rather than restarting each time. Being mid-booking never
    # traps the visitor from asking something else - see _will_override_reply.
    if session.get("registered"):
        cancelling = session.get("booking_active") and re.search(
            r"\b(cancel|never mind|forget it|nevermind)\b", transcript, re.IGNORECASE
        )
        if cancelling:
            session["booking_active"] = False
            session["booking"] = {}
            reply_text = "No problem - just let me know if you'd like to book something else."
        elif action == "booking_intent" or session.get("booking_active"):
            booking = session.setdefault("booking", {})
            parsed = None
            try:
                with SessionLocal() as db:
                    parsed = await parse_booking_intent(db, transcript, service_type=session.get("service_type"))
            except Exception as e:
                log_error(f"Booking intent parse error: {e}")

            found_new_detail = False
            if parsed:
                for key in ("zone_id", "zone_name", "booking_date", "booking_time_start", "duration_minutes"):
                    value = getattr(parsed, key, None)
                    if not value:
                        continue
                    found_new_detail = True
                    if key == "booking_time_start":
                        booking[key] = value.strftime("%H:%M")
                    elif hasattr(value, "isoformat"):
                        booking[key] = value.isoformat()
                    else:
                        booking[key] = value

            if action != "booking_intent" and session.get("booking_active") and not found_new_detail:
                pass
            else:
                session["booking_active"] = True
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

    return reply_text, action


async def _try_synthesize(text: str) -> tuple[str | None, str | None]:
    """TTS is a nice-to-have, not the core function - any failure here
    (unavailable, timeout, connection error, etc.) falls back to a
    text-only reply rather than breaking the whole conversation turn.
    The frontend already falls back to browser speech synthesis whenever
    reply_audio comes back empty."""
    try:
        audio_bytes, content_type = await synthesize_speech(text)
        return base64.b64encode(audio_bytes).decode("utf-8"), content_type
    except Exception as tts_exc:
        log_error(f"TTS failed, falling back to text-only reply: {tts_exc}")
        return None, None


def _fallback_llm_data(session: dict) -> dict:
    return {
        "reply": "I'm sorry, I didn't understand. Could you please repeat that?",
        "action": "retry",
        "extracted": {},
        "missing": session.get("missing", ["name", "email", "visitor_type", "phone"]),
    }


@router.post("/converse")
async def converse(request: ConverseRequest):
    session = _prepare_session(request)

    # Snapshot registration state *after* the pre-authentication shortcut
    # above but *before* this turn's login/register handling runs. This is
    # what lets us tell "was already registered coming into this turn"
    # (an already-known visitor greeted on a new page) apart from "this
    # turn is the one that just completed login/registration" - only the
    # latter should tell the frontend to wrap up and hand off.
    was_registered_before_this_turn = session.get("registered", False)

    transcript, error_reply, error_step = await _extract_transcript(request)
    if error_reply:
        audio_b64, content_type = await _try_synthesize(error_reply)
        return {
            "session_id": request.session_id,
            "reply_text": error_reply,
            "reply_audio": audio_b64,
            "audio_content_type": content_type,
            "session_ended": False,
            "registered": session.get("registered", False),
            "just_registered": False,
            "extracted": None,
            "step": error_step,
        }

    llm_data = await get_next_response(transcript, session)
    _merge_extracted_into_session(session, llm_data.get("extracted", {}))
    session["missing"] = llm_data.get("missing", [])

    action = llm_data.get("action", "retry")
    reply_text = llm_data.get("reply", "Processing...")
    action = _resolve_action(session, action)

    reply_text, action = await _run_business_logic(session, action, transcript, reply_text)
    log_info(f"Final reply (after business logic) - action={action!r} registered={session.get('registered')} booking_active={session.get('booking_active')}: {reply_text!r}")

    audio_b64, content_type = await _try_synthesize(reply_text)

    booking_ready_now = session.get("booking_ready", False)
    if booking_ready_now:
        # One-shot signal - the frontend hands off to the manual booking
        # form to confirm, so don't keep repeating this once it's been sent.
        session["booking_ready"] = False

    just_registered_now = session.get("registered", False) and not was_registered_before_this_turn
    session_ended_now = action == "done"

    if (just_registered_now or booking_ready_now or session_ended_now) and request.session_id:
        await close_xai_tts_session(request.session_id)

    return {
        "session_id": request.session_id,
        "reply_text": reply_text,
        "reply_audio": audio_b64,
        "audio_content_type": content_type,
        "session_ended": session_ended_now,
        "registered": session.get("registered", False),
        "just_registered": just_registered_now,
        "booking_ready": booking_ready_now,
        "extracted": {
            **{k: session[k] for k in ["name", "email", "phone", "visitor_type"] if session.get(k)},
            **session.get("booking", {}),
        },
        "step": action,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/converse/stream")
async def converse_stream(request: ConverseRequest):
    """
    Streaming counterpart to /converse: sends audio back as a sequence of
    Server-Sent Events as it's generated, instead of one complete blob at
    the end - so playback can start before the full reply exists.

    Event shapes (each a `data: {...}` SSE line):
      {"type": "audio_chunk", "audio": "<base64>", "content_type": "..."}
      {"type": "final", ...same fields as /converse's JSON response...}

    Only actually streams audio incrementally when tts_provider is "xai"
    (the only provider with a real-time streaming protocol here) AND this
    turn's reply won't be overridden by business logic afterward (see
    _will_override_reply) - e.g. login/register/booking-completion replies
    are generated server-side after the LLM finishes, so there's nothing to
    stream early for those; they still work, just via one audio_chunk
    event instead of many.
    """
    session = _prepare_session(request)
    was_registered_before_this_turn = session.get("registered", False)
    transcript, error_reply, error_step = await _extract_transcript(request)

    async def event_stream():
        if error_reply:
            audio_b64, content_type = await _try_synthesize(error_reply)
            yield _sse({
                "type": "final",
                "session_id": request.session_id,
                "reply_text": error_reply,
                "reply_audio": audio_b64,
                "audio_content_type": content_type,
                "session_ended": False,
                "registered": session.get("registered", False),
                "just_registered": False,
                "booking_ready": False,
                "extracted": None,
                "step": error_step,
            })
            return

        state = {"action": "retry", "final_data": None, "overridden": False}

        async def safe_text_chunks():
            """Drains stream_next_response, merging extracted into session
            as soon as the header arrives, and yielding text chunks for TTS
            only while this turn's reply is safe to speak as-is (i.e. won't
            get overridden by business logic afterward)."""
            async for event in stream_next_response(transcript, session):
                etype = event["type"]
                if etype == "header":
                    header = event["data"]
                    _merge_extracted_into_session(session, header.get("extracted", {}))
                    session["missing"] = header.get("missing", [])
                    state["action"] = _resolve_action(session, header.get("action", "retry"))
                    state["overridden"] = _will_override_reply(session, state["action"], transcript)
                elif etype == "text_delta":
                    if not state["overridden"]:
                        yield event["text"]
                elif etype in ("done", "error"):
                    state["final_data"] = event["data"]
                    if etype == "error":
                        state["action"] = event["data"].get("action", "retry")

        streaming_tts_available = settings.tts_enabled and settings.tts_provider == "xai"

        if streaming_tts_available:
            try:
                async for audio_chunk in stream_synthesize_xai(safe_text_chunks(), session_id=request.session_id):
                    if state["overridden"] or not audio_chunk:
                        continue
                    content_type = (
                        "audio/mpeg" if settings.xai_tts_codec == "mp3" else f"audio/{settings.xai_tts_codec}"
                    )
                    yield _sse({
                        "type": "audio_chunk",
                        "audio": base64.b64encode(audio_chunk).decode("utf-8"),
                        "content_type": content_type,
                    })
            except Exception as tts_exc:
                # Streaming TTS failed mid-turn - we still have (or will
                # shortly have) the full reply text below, just synthesized
                # as one clip instead of streamed.
                log_error(f"Streaming TTS failed, falling back to one-shot synthesis: {tts_exc}")
        else:
            # No streaming TTS available - just drain the text generator
            # so we still reach "done"/"error" and get the full reply.
            async for _ in safe_text_chunks():
                pass

        final_data = state["final_data"] or _fallback_llm_data(session)
        action = final_data.get("action", state["action"])
        action = _resolve_action(session, action)
        reply_text = final_data.get("reply", "Processing...")

        reply_text, action = await _run_business_logic(session, action, transcript, reply_text)
        log_info(
            f"Final reply (after business logic) - action={action!r} overridden={state['overridden']} "
            f"registered={session.get('registered')} booking_active={session.get('booking_active')}: {reply_text!r}"
        )

        # The reply text is known now (whether or not it was overridden).
        # If we can stream TTS, do so even for an overridden reply - the
        # text itself is fixed, but audio playback can still start as soon
        # as synthesis begins instead of waiting for the whole clip. Only
        # fall back to a fully-buffered one-shot clip if streaming TTS
        # isn't available at all, or the streamed attempt fails mid-way.
        final_audio_b64 = None
        final_content_type = None
        if streaming_tts_available and state["overridden"]:
            async def _single_chunk(text: str):
                yield text

            streamed_any = False
            try:
                async for audio_chunk in stream_synthesize_xai(_single_chunk(reply_text), session_id=request.session_id):
                    if not audio_chunk:
                        continue
                    streamed_any = True
                    content_type = (
                        "audio/mpeg" if settings.xai_tts_codec == "mp3" else f"audio/{settings.xai_tts_codec}"
                    )
                    yield _sse({
                        "type": "audio_chunk",
                        "audio": base64.b64encode(audio_chunk).decode("utf-8"),
                        "content_type": content_type,
                    })
            except Exception as tts_exc:
                log_error(f"Streaming TTS for overridden reply failed, falling back to one-shot synthesis: {tts_exc}")

            if not streamed_any:
                final_audio_b64, final_content_type = await _try_synthesize(reply_text)
        elif not streaming_tts_available:
            final_audio_b64, final_content_type = await _try_synthesize(reply_text)

        booking_ready_now = session.get("booking_ready", False)
        if booking_ready_now:
            session["booking_ready"] = False
        just_registered_now = session.get("registered", False) and not was_registered_before_this_turn
        session_ended_now = action == "done"

        if (just_registered_now or booking_ready_now or session_ended_now) and request.session_id:
            # Conversation's wrapping up here - the frontend hands off and
            # closes the modal, so release the cached TTS connection now
            # instead of leaving it open until it eventually times out.
            await close_xai_tts_session(request.session_id)

        yield _sse({
            "type": "final",
            "session_id": request.session_id,
            "reply_text": reply_text,
            "reply_audio": final_audio_b64,
            "audio_content_type": final_content_type,
            "session_ended": session_ended_now,
            "registered": session.get("registered", False),
            "just_registered": just_registered_now,
            "booking_ready": booking_ready_now,
            "extracted": {
                **{k: session[k] for k in ["name", "email", "phone", "visitor_type"] if session.get(k)},
                **session.get("booking", {}),
            },
            "step": action,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")