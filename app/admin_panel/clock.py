from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC time, matching the DateTime columns (no tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
