"""Last Spacebring sync outcome, kept in memory for the dashboard."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_state: dict = {"last_run_at": None, "ok": None, "created": 0, "updated": 0, "deleted": 0, "error": None}


def record_ok(result) -> None:
    with _lock:
        _state.update(
            last_run_at=datetime.now(timezone.utc).isoformat(), ok=True, error=None,
            created=result.created, updated=result.updated, deleted=result.deleted,
        )


def record_error(message: str) -> None:
    with _lock:
        _state.update(last_run_at=datetime.now(timezone.utc).isoformat(), ok=False, error=message[:200])


def snapshot() -> dict:
    with _lock:
        return dict(_state)
