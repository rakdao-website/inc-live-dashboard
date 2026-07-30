import google.generativeai as genai
from app.config import settings

genai.configure(api_key=settings.gemini_api_key)  # Set the API key for the Gemini model
model = genai.GenerativeModel(settings.gemini_model)


# services/session_manager.py

sessions = {}

def create_session(session_id: str, name: str = None, email: str = None, existing_customer: bool = None):
    chat = model.start_chat(history=[])
    sessions[session_id] = {
        "name": name,
        "email": email,
        "existing_customer": existing_customer,
        "chat": chat,
        "registered": False,        # new flag
    }
    return sessions[session_id]

def get_session(session_id: str):
    return sessions.get(session_id)

def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]

def update_session(session_id: str, name: str = None, email: str = None, existing_customer: bool = None):
    session = get_session(session_id)
    if session:
        if name is not None:
            session["name"] = name
        if email is not None:
            session["email"] = email
        if existing_customer is not None:
            session["existing_customer"] = existing_customer
        session["registered"] = bool(name and email and existing_customer is not None)
