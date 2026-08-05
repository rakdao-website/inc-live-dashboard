sessions = {}

def create_session(session_id: str, visitor_id: int = None):
    sessions[session_id] = {
        "visitor_id": visitor_id,
        "name": None,
        "email": None,
        "phone": None,
        "visitor_type": None,
        "registered": False,
        #conversation state
        "collected":{},
        "missing" : ["name", "email", "visitor_type", "phone"],
        "step": "greeting"
    }
    return sessions[session_id]

def get_session(session_id: str):
    return sessions.get(session_id)

def update_session(session_id: str, **kwargs):
    session = get_session(session_id)
    if not session:
        return
    for key, value in kwargs.items():
        session[key] = value
        
def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]