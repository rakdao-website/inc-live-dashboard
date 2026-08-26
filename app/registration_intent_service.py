import json
import re
from datetime import datetime
import httpx
from app.config import settings
from app.kiosk_flow_services import normalize_phone

LLM_TIMEOUT_SECONDS = 10
 
_EMAIL_LITERAL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_EMAIL_SPOKEN_RE = re.compile(
    r"([a-zA-Z0-9]+(?:\s+dot\s+[a-zA-Z0-9]+)*)\s+at\s+([a-zA-Z0-9]+(?:\s+dot\s+[a-zA-Z0-9]+)+)",
    re.IGNORECASE,
)
# A plausible phone number: 7-15 digits, allowing spaces/dashes/parens between them.
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{5,18}\d)")
 
_VISITOR_TYPE_CLIENT_RE = re.compile(r"\b(existing client|already a client|i'?m a client)\b", re.IGNORECASE)
_VISITOR_TYPE_VISITOR_RE = re.compile(r"\b(new visitor|first time|not a client)\b", re.IGNORECASE)

class ParsedVisitor:
    def __init__(self):
        self.full_name: str | None = None
        self.mobile_number: str | None = None
        self.email: str | None = None
        self.company_name: str | None = None
        self.visitor_type: str | None = None  # "client" | "visitor"
        self.name_source: str = "none"  # "llm" | "none"
        self.missing: list[str] = []
 
    def to_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "mobile_number": self.mobile_number,
            "email": self.email,
            "company_name": self.company_name,
            "visitor_type": self.visitor_type,
            "name_source": self.name_source,
            "missing": self.missing,
        }


def _extract_phone(transcript: str):
    match = _PHONE_RE.search(transcript)
    if not match:
        return None,None
    digit_count = sum(c.isdigit() for c in match.group(1))
    if digit_count < 7:
        return None,None
    normalized = normalize_phone(match.group(1))
    return (normalized or None), match.group(0)

def _extract_email(trasnscript:str):
    literal = _EMAIL_LITERAL_RE.search(trasnscript)
    if literal:
        return literal.group(0), literal.group(0)

    spoken = _EMAIL_SPOKEN_RE.search(trasnscript)
    if spoken:
        local = re.sub(r"\s+dot\s+", ".", spoken.group(1), flags=re.IGNORECASE)
        domain = re.sub(r"\s+dot\s+", ".", spoken.group(2), flags=re.IGNORECASE)
        email = f"{local}@{domain}".lower().replace(" ", "")
        return email, spoken.group(0)
    return None,None


def _extract_visitor_type(transcript: str):
    if _VISITOR_TYPE_CLIENT_RE.search(transcript):
        return "client"
    if _VISITOR_TYPE_VISITOR_RE.search(transcript):
        return "visitor"
    return None

def _mask(transcript:str,*substrings:str | None) -> str:
    masked = transcript
    for s in substrings:
        if s:
            masked = masked.replace(s, " ")
    return masked

async def   _extract_name_and_company_llm(masked_transcript: str) -> dict:
    prompt = (
        "Extract the speaker's own full name and, if mentioned, their company "
        "name from this sentence. This is a visitor check-in kiosk, so if "
        "multiple names appear, prefer the one introduced with phrasing like "
        '"I\'m", "my name is", or "this is". Respond with ONLY a JSON object, '
        'no other text: {"full_name": "..." or null, "company_name": "..." or '
        f"null}}.\n\nSentence: {masked_transcript}"
    )
    raw = None
    try:
        if settings.room_question_provider == "gemini" and settings.gemini_api_key:
            raw = await _call_gemini(prompt)
        elif settings.room_question_provider == "grok" and settings.xai_api_key:
            raw = await _call_grok(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"Name/company LLM extraction failed: {exc}")
        return {}
 
    if not raw:
        return {}
 
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except Exception as exc:  # noqa: BLE001
        print(f"Name/company LLM response unparsable: {exc}")
        return {}
 
async def _call_gemini(prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=body)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
 
 
async def _call_grok(prompt: str) -> str:
    headers = {"Authorization": f"Bearer {settings.xai_api_key}"}
    body = {"model": settings.xai_model, "messages": [{"role": "user", "content": prompt}]}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post("https://api.x.ai/v1/chat/completions", json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def parse_visitor_intent(transcript: str) -> ParsedVisitor:
    """Used for BOTH registration (full result) and returning-visitor lookup
    (caller just reads .full_name and .mobile_number, ignores the rest)."""
    result = ParsedVisitor()
 
    phone, phone_match = _extract_phone(transcript)
    result.mobile_number = phone
    email, email_match = _extract_email(transcript)
    result.email = email
    result.visitor_type = _extract_visitor_type(transcript)
 
    # Only the minimum needed for name/company extraction reaches the LLM -
    # phone and email are already reliably extracted above, so there's no
    # reason to also send them.
    masked = _mask(transcript, phone_match, email_match)
    extracted = await _extract_name_and_company_llm(masked)
    if extracted.get("full_name"):
        result.full_name = extracted["full_name"]
        result.name_source = "llm"
    if extracted.get("company_name"):
        result.company_name = extracted["company_name"]
 
    if not result.full_name:
        result.missing.append("full_name")
    if not result.mobile_number:
        result.missing.append("mobile_number")
    if not result.email:
        result.missing.append("email")
 
    return result


