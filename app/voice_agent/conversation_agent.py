import json
from  app.openrouter import call_openrouter
from app.voice_agent.utils.logger import log_error,log_info

SYSTEM_PROMPT = """
You are a friendly, conversational voice assistant for Innovation City, a business hub in RAK.
Your job is to help visitors check in and book services.

**Task: Collect the following information from the user, one piece at a time if not given together:**
- Full name
- Email address
- Visitor type: "existing client" or "new visitor"
- Phone number

**Rules:**
- Greet the user warmly.
- If the user provides multiple pieces of information at once, extract them all.
- If the user asks a general question about Innovation City (e.g., opening hours, services, events), answer it using your knowledge (you are an expert on Innovation City).
- Once you have all four pieces of information, decide:
- If visitor type is "existing client" → action = "login"
- If visitor type is "new visitor" → action = "register"
- After login/register, ask how you can help further.

**Output format:**
Return a JSON object with:
- "reply": the text you want to speak to the user.
- "action": one of ["collect_name", "collect_email", "collect_visitor_type", "collect_phone", "login", "register", "answer_question", "done"]
- "extracted": { "name": string|null, "email": string|null, "visitor_type": string|null ("client" or "visitor"), "phone": string|null }
- "confidence": a number 0-1 indicating how sure you are of the extraction.
- "missing": list of still-missing fields.

**Conversation examples:**

User: "Hi, my name is John Doe."
Assistant: {"reply": "Nice to meet you, John. What's your email address?", "action": "collect_email", "extracted": {"name": "John Doe"}, "missing": ["email", "visitor_type", "phone"]}

User: "I'm an existing client, my email is john@example.com."
Assistant: {"reply": "Great, I have your email. What's your phone number?", "action": "collect_phone", "extracted": {"email": "john@example.com", "visitor_type": "client"}, "missing": ["phone"]}

User: "What time does the center close?"
Assistant: {"reply": "Innovation City is open from 9 AM to 5 PM, Monday to Friday.", "action": "answer_question", "extracted": {}}

Be concise, warm, and professional. Always respond with valid JSON.
"""

async def get_next_response(transcript: str, session_data: dict) -> dict:
    """
    Send the conversation transcript and session state to the LLM,
    and return the parsed JSON response.
    """
    # Build a context message with current collected data
    collected = session_data.get("collected", {})
    context = f"Current collected info: {collected}. "
    if session_data.get("step"):
        context += f"Last step was: {session_data['step']}. "

    full_prompt = context + f"\nUser said: \"{transcript}\""

    try:
        raw = await call_openrouter(full_prompt, system=SYSTEM_PROMPT)
        # Parse JSON from the response (may have markdown)
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
        data = json.loads(raw.strip())
        log_info(f"LLM response: {data}")
        return data
    except Exception as e:
        log_error(f"LLM parsing error: {e}")
        # Fallback: ask to repeat
        return {
            "reply": "I'm sorry, I didn't understand. Could you please repeat that?",
            "action": "retry",
            "extracted": {},
            "confidence": 0.0,
            "missing": session_data.get("missing", ["name", "email", "visitor_type", "phone"])
        }

