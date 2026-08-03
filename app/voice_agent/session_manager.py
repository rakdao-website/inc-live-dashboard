sessions = {}

def create_session(session_id: str, name: str = None, email: str = None, phone: str = None, existing_customer: bool = None):
    sessions[session_id] = {
        "name": name,
        "email": email,
        "phone": phone,
        "existing_customer": existing_customer,
        "registered": False,
    }
    return sessions[session_id]

def get_session(session_id: str):
    return sessions.get(session_id)

def update_session(session_id: str, **kwargs):
    session = get_session(session_id)
    if session:
        for key, value in kwargs.items():
            session[key] = value
        # Mark registered if we have all required fields
        if session.get("name") and session.get("email") and session.get("existing_customer") is not None:
            session["registered"] = True
        if session.get("name") and session.get("phone"):
            session["logged_in"] = True

def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]