"""Loads knowledge_base.md, shared by both the text pipeline
(conversation_agent.py) and the Realtime voice agent (realtime_auth.py).

Deliberately has NO dependency on any LLM client (openrouter.py,
xai_client.py) -- those modules read API-key settings at import time, and
the Realtime agent's whole point is that it doesn't need a text-pipeline
LLM configured at all. Keeping this loader dependency-free means
realtime_auth.py can serve the knowledge base without ever pulling in
OpenRouter/xAI machinery it doesn't use.
"""

import os

from app.voice_agent.utils.logger import log_error

# The knowledge base lives in its own document (knowledge_base.md, next to
# this file) instead of a hardcoded string, so non-engineers can update the
# facts the assistant answers questions from without touching code. It's
# re-read on every request (see load_knowledge_base), so edits take effect
# immediately - no restart or redeploy needed.
_KNOWLEDGE_BASE_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.md")

_FALLBACK_KNOWLEDGE_BASE = (
    "(Knowledge base document is currently unavailable. Tell the visitor you're "
    "not sure and suggest they ask a reception associate for details.)"
)

_kb_cache: dict = {"mtime": None, "content": None}


def load_knowledge_base() -> str:
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