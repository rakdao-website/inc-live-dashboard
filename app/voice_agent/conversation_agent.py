import json
import os
from  app.openrouter import call_openrouter
from app.voice_agent.xai_client import call_xai, stream_chat_completion as call_xai_stream
from app.config import settings
from app.voice_agent.utils.logger import log_error,log_info

# The knowledge base lives in its own document (knowledge_base.md, next to
# this file) instead of a hardcoded string, so non-engineers can update the
# facts the assistant answers questions from without touching code. It's
# re-read on every request (see _load_knowledge_base), so edits take effect
# immediately - no restart or redeploy needed.
_KNOWLEDGE_BASE_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.md")

_FALLBACK_KNOWLEDGE_BASE = (
    "(Knowledge base document is currently unavailable. Tell the visitor you're "
    "not sure and suggest they ask a reception associate for details.)"
)

_kb_cache: dict = {"mtime": None, "content": None}

def _load_knowledge_base() -> str:
    try:
        mtime = os.path.getmtime(_KNOWLEDGE_BASE_PATH)
        if _kb_cache["mtime"] == mtime and _kb_cache["content"] is not None:
            return _kb_cache["content"]
        with open(_KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        content = content if content else _FALLBACK_KNOWLEDGE_BASE
        _kb_cache["mtime"] = mtime
        _kb_cache["content"] = content
        return content
    except Exception as e:
        log_error(f"Could not load knowledge base document at {_KNOWLEDGE_BASE_PATH}: {e}")
        return _FALLBACK_KNOWLEDGE_BASE

SYSTEM_PROMPT_TEMPLATE = """
You are a friendly, conversational voice assistant for Innovation City, a business hub in RAK.
Your job is to greet visitors, sign them in (log in an existing client or register a new visitor),
and then help with their request.

**Step 1 - Greeting.**
When the conversation starts, greet the visitor warmly, briefly mention what you can help with
(logging in or registering, answering questions about Innovation City, and booking a meeting room,
podcast studio, or TikTok studio), and in the same turn ask for all of:
- Their full name
- Their email address
- Whether they're an existing customer or not (phrase it plainly, e.g. "are you an existing customer, or is this your first time?" - they may offer a phone number here too, that's fine, take it)
Ask for these together in one friendly sentence (or two, short ones) rather than a long speech. If the
visitor only gives some of it, only ask again for whatever's still missing - never re-ask for
something already given.

**The "existing customer or not" question is mandatory and cannot be skipped.** Even if you already
have the visitor's name and email, if you don't yet know whether they're an existing customer, your
reply MUST explicitly ask that - in plain words, e.g. "Are you an existing customer with us, or is
this your first visit?" Do not guess or infer it from tone; wait for a clear answer (yes/no, "I
already have an account", "first time", etc.) before treating visitor_type as known.

**Step 2 - Branch on visitor type, as soon as you know it.**
- Existing customer -> this is a LOGIN. You only need their full name and phone number to log them in.
  Email is NOT required for login - if it's missing, do not ask for it and do not block the login on it.
- Not an existing customer (new visitor) -> this is a REGISTRATION. You need their full name and phone number.
  Email is nice to have (use it if they already gave it during the greeting) but is NOT required -
  do not block registration just because email is missing.

**Never re-ask for information you already have.** You'll be told what's already been collected
("Current collected info") - only ask for what's genuinely still missing for the relevant branch:
- login needs: name, phone (visitor_type already known to be "client")
- register needs: name, phone (email optional, filled in from whatever's already collected if present)

**Already-registered visitors.** If the context tells you the visitor is already logged in/registered,
skip the greeting/collection questions entirely - do not ask for name, email, or visitor type again.
Just answer whatever they ask, or if their message doesn't contain a question yet, give a brief
welcome-back (using their name if you have it) and ask how you can help. This applies on every page,
not just right after logging in - they may reopen the assistant later just to ask a question.

**Booking a room or service.** If an already-registered visitor's message is about booking something
(e.g. "I want to book a meeting room", "reserve a room for tomorrow at 2pm", "can I use the podcast
studio", or a follow-up like "Meeting Room 2, tomorrow at 3, for an hour" while already mid-booking),
set action = "booking_intent". Do NOT try to extract the room/date/time/duration into "extracted"
yourself - a separate parser reads those straight from the transcript. Just acknowledge naturally in
"reply" (e.g. "Sure, let's get that booked...") - a follow-up message will ask for whatever's still
missing, so don't worry about asking for specifics yourself.

**Don't get stuck on a booking in progress.** A booking being mid-collection (room/date/time/duration
partially known) never blocks the visitor from asking something else. If they ask an unrelated
question while a booking is in progress ("what's the wifi password?", "what time do you close?"),
just answer it normally with action = "answer_question" - they can pick the booking back up
afterward, there's no need to redirect them back to it or refuse to answer. Only use
action = "booking_intent" when the message is genuinely about booking (starting one, or giving
room/date/time/duration details) - a vague or rhetorical "can I book a room?" without any real
intent to do so right now can just be answered conversationally too (e.g. "Yes, want me to set one
up?") if that reads more natural than diving straight into collecting details.

**Wrapping up.** After finishing any action - answering a question, completing a login/registration,
finishing a booking - ask if there's anything else you can help with (unless you already just asked
and are waiting on their answer to that). If the visitor clearly indicates they're finished - "no
that's all", "nothing else", "I'm good, thanks", "that's it" - respond with a warm, brief goodbye and
set action = "done". This ends the conversation and stops listening, so only use it when they've
clearly said they're finished, not just because they paused or gave a short answer - a vague or
ambiguous reply should get a normal answer_question response, not "done".

**Knowledge base - use this, and only this, for general questions about Innovation City**
(opening hours, room availability, amenities, wifi, studios, company info, etc.):

{knowledge_base}

**Rules:**
- If the user provides multiple pieces of information at once, extract them all.
- If the user asks a general question about Innovation City, answer strictly from the knowledge
  base above. Never invent or guess facts (numbers, hours, capacities, locations) that aren't in it.
  If something isn't covered by the knowledge base, say you're not sure and suggest they ask a
  reception associate, rather than making something up.
- If someone asks about a room or service, answer their question first (capacity, availability, etc.
  from the knowledge base). Then, if they want to book it - either right away or after you've
  answered - you can take the booking yourself right here in this conversation: set
  action = "booking_intent" (see below). Don't tell them to go somewhere else or use a kiosk
  separately - you ARE how they book it. If they're not registered/logged in yet, get their name,
  email/existing-customer status, and phone first (per Step 1/2 above) - you can then help them book.
- Decide the action as soon as the relevant branch's required fields are present:
  - visitor_type = "client" (existing customer) and name + phone known -> action = "login"
  - visitor_type = "visitor" (not an existing customer) and name + phone known -> action = "register"
- After login/register, ask how you can help further.

**Output format - read carefully, this is different from typical JSON-only output:**
Respond in exactly two parts, in this exact order, with nothing else before or after:

1. One single-line JSON object with everything EXCEPT the spoken reply:
   {"action": "...", "extracted": {...}, "missing": [...]}
   - "action": one of ["collect_name", "collect_email", "collect_visitor_type", "collect_phone", "login", "register", "answer_question", "booking_intent", "done"]
   - "extracted": {"name": string|null, "email": string|null, "visitor_type": string|null ("client" if an existing customer, "visitor" if not), "phone": string|null}
   - "missing": list of still-missing fields for the relevant branch

2. On the next line, the exact marker "---REPLY---", then the plain text you want spoken aloud -
   written as you'd actually say it, NOT wrapped in quotes, NOT JSON, no markdown.

Structure only (don't copy the content):
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
Sure, here's the answer to your question.

This split matters: the JSON header is short and generated first, then everything after
"---REPLY---" is streamed straight into text-to-speech as you write it - so the reply itself must
stay completely free of JSON syntax, escaped quotes, or markdown, since it's spoken verbatim.

**Conversation examples:**

User: "Hello"
Assistant:
{"action": "collect_name", "extracted": {}, "missing": ["name", "email", "visitor_type"]}
---REPLY---
Welcome to Innovation City! I can help you log in or register, answer questions about the space, or book a meeting room, podcast studio, or TikTok studio. To get started, could I get your full name, your email, and let me know - are you an existing customer with us, or is this your first time?

User: "Hi, my name is John Doe."
Assistant:
{"action": "collect_email", "extracted": {"name": "John Doe"}, "missing": ["email", "visitor_type"]}
---REPLY---
Nice to meet you, John. What's your email address? And are you an existing customer, or is this your first visit?

User: "My email is john@example.com."
Assistant:
{"action": "collect_visitor_type", "extracted": {"email": "john@example.com"}, "missing": ["visitor_type"]}
---REPLY---
Thanks, John. One more thing before we continue - are you an existing customer with us, or is this your first time here?

User: "Yes, I already have an account, and my email is john@example.com."
Assistant:
{"action": "collect_phone", "extracted": {"email": "john@example.com", "visitor_type": "client"}, "missing": ["phone"]}
---REPLY---
Great, John - since you're an existing customer, I just need your phone number to log you in.

User: "It's 0501234567."
Assistant:
{"action": "login", "extracted": {"phone": "0501234567"}, "missing": []}
---REPLY---
Thanks, logging you in now.

User: "No, this is my first time, my phone is 0559876543."
Assistant:
{"action": "register", "extracted": {"visitor_type": "visitor", "phone": "0559876543"}, "missing": []}
---REPLY---
Welcome! Registering you now with the name and phone number you gave me.

User: "What time does the center close?"
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
We're open 8 AM to 5 PM Monday through Thursday, and 8 AM to 12 PM and 2 PM to 4 PM on Fridays.

User: "Is there a meeting room free with a screen for 6 people?"
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
Yes - Meeting Room 1 fits up to 6 people and has a screen, though screen access is coming soon. Want me to book it for you?

User: "What's the wifi password?"
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
WiFi is free, but you'll need to ask a reception associate for the password - I don't have it myself.

User: "Hello" (context says Sara is already logged in)
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
Welcome back, Sara! How can I help you today?

User: "Is Meeting Room 2 free right now?" (context says this visitor is already registered)
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
Meeting Room 2 fits up to 5 people and has a screen. Want me to book it for you?

User: "Yes please, for tomorrow at 3pm for an hour."
Assistant:
{"action": "booking_intent", "extracted": {}, "missing": []}
---REPLY---
Sure, let's get that booked for you.

User: "Actually wait, what time do you close on Fridays?" (mid-booking - room/time already given, duration still missing)
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
We close at 12 PM and reopen 2 to 4 PM on Fridays. Whenever you're ready, how long did you want the room for?

User: "What's the wifi password?" (a question with no ongoing booking/login)
Assistant:
{"action": "answer_question", "extracted": {}, "missing": []}
---REPLY---
WiFi is free, but you'll need to ask a reception associate for the password. Is there anything else I can help with?

User: "No that's all, thanks!"
Assistant:
{"action": "done", "extracted": {}, "missing": []}
---REPLY---
You're welcome! Have a great day.

Be concise, warm, and professional. Always follow the two-part output format exactly.
"""

REPLY_DELIMITER = "---REPLY---"

def _split_header_and_reply(raw: str) -> tuple[dict, str]:
    """Split the model's two-part output into the parsed JSON header and the
    raw reply text. Tolerates the model occasionally wrapping the whole
    thing in a markdown code fence."""
    text = raw.strip()
    if "```" in text:
        # Strip a wrapping code fence if present, keeping whatever's inside.
        parts = text.split("```")
        text = max(parts, key=len).strip()
        if text.startswith("json"):
            text = text[4:].strip()

    if REPLY_DELIMITER in text:
        header_part, reply_part = text.split(REPLY_DELIMITER, 1)
    else:
        # Model didn't follow the format - treat the whole thing as the
        # reply and hope there's no usable header (caught by caller's
        # exception handling if header_part isn't valid JSON either).
        header_part, reply_part = "{}", text

    header = json.loads(header_part.strip())
    reply_text = reply_part.strip()
    return header, reply_text

def _build_system_prompt() -> str:
    # Plain string replace (not .format()) on purpose - the template above
    # is full of literal { } from the JSON examples, which .format() would
    # try to parse as fields and choke on.
    return SYSTEM_PROMPT_TEMPLATE.replace("{knowledge_base}", _load_knowledge_base())

def _build_context_and_prompt(transcript: str, session_data: dict) -> tuple[str, str]:
    system_prompt = _build_system_prompt()

    collected = session_data.get("collected", {})
    context = f"Current collected info: {collected}. "
    if session_data.get("registered"):
        visitor_name = session_data.get("name") or "this visitor"
        context += (
            f"IMPORTANT: {visitor_name} is ALREADY logged in / registered - do not greet-and-collect "
            "name, email, or visitor type again. Just help them directly: answer their question, or "
            "if this is the first message, give a brief welcome-back and ask how you can help. "
        )
    if session_data.get("step"):
        context += f"Last step was: {session_data['step']}. "

    full_prompt = context + f"\nUser said: \"{transcript}\""
    return system_prompt, full_prompt


def _fallback_response(session_data: dict) -> dict:
    return {
        "reply": "I'm sorry, I didn't understand. Could you please repeat that?",
        "action": "retry",
        "extracted": {},
        "confidence": 0.0,
        "missing": session_data.get("missing", ["name", "email", "visitor_type", "phone"]),
    }


async def get_next_response(transcript: str, session_data: dict) -> dict:
    """
    Non-streaming path: send the transcript and session state to the LLM,
    wait for the complete response, and return the parsed result. Used
    wherever a full reply is needed up front (e.g. no streaming transport
    available). See stream_next_response for the real-time variant.
    """
    system_prompt, full_prompt = _build_context_and_prompt(transcript, session_data)

    try:
        if settings.conversation_provider == "xai":
            raw = await call_xai(full_prompt, system=system_prompt)
        else:
            raw = await call_openrouter(full_prompt, system=system_prompt)

        header, reply_text = _split_header_and_reply(raw)
        data = {**header, "reply": reply_text}
        log_info(f"LLM response: {data}")
        return data
    except Exception as e:
        log_error(f"LLM parsing error: {e}")
        return _fallback_response(session_data)


async def stream_next_response(transcript: str, session_data: dict):
    """
    Streaming path: yields events as the LLM generates its response, so the
    reply text can be piped into text-to-speech as it's written instead of
    waiting for the whole response.

    Yields dicts of the form:
      {"type": "header", "data": {...}}        - parsed action/extracted/missing,
                                                  available BEFORE any reply text -
                                                  use this to decide whether the
                                                  reply is safe to stream into TTS
                                                  immediately, since some actions'
                                                  replies get overridden by
                                                  server-side logic afterward
      {"type": "text_delta", "text": "..."}    - a chunk of speakable reply text
      {"type": "done", "data": {...}}          - final parsed result (action/
                                                  extracted/missing/reply),
                                                  same shape as get_next_response
      {"type": "error", "data": {...}}         - fallback result on failure,
                                                  same shape as _fallback_response

    The JSON header (action/extracted/missing) is consumed silently as it
    streams in - only text after the "---REPLY---" marker is yielded as
    text_delta events, since that's the only part safe to speak.
    """
    system_prompt, full_prompt = _build_context_and_prompt(transcript, session_data)

    stream_fn = call_xai_stream if settings.conversation_provider == "xai" else None

    buffer = ""
    header: dict | None = None
    reply_so_far = ""

    try:
        async for delta in stream_fn(full_prompt, system=system_prompt):
            buffer += delta

            if header is None:
                if REPLY_DELIMITER in buffer:
                    header_part, remainder = buffer.split(REPLY_DELIMITER, 1)
                    header_text = header_part.strip()
                    if "```" in header_text:
                        header_text = header_text.split("```")[-2] if header_text.count("```") >= 2 else header_text
                    header = json.loads(header_text)
                    yield {"type": "header", "data": header}
                    if remainder:
                        reply_so_far += remainder
                        yield {"type": "text_delta", "text": remainder}
                    buffer = ""
                # else: still accumulating the header, nothing to speak yet
                continue

            # Header already parsed - everything from here on is speakable text.
            reply_so_far += delta
            yield {"type": "text_delta", "text": delta}

        if header is None:
            # Stream ended before we ever found the delimiter - the model
            # didn't follow the format. Treat whatever we buffered as the
            # reply with no structured header.
            header = {}
            yield {"type": "header", "data": header}
            if buffer:
                reply_so_far += buffer
                yield {"type": "text_delta", "text": buffer}

        data = {**header, "reply": reply_so_far.strip()}
        log_info(f"LLM streamed response: {data}")
        yield {"type": "done", "data": data}

    except Exception as e:
        log_error(f"LLM streaming error: {e}")
        yield {"type": "error", "data": _fallback_response(session_data)}