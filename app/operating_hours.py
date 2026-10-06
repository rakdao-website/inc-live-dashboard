from datetime import time

from app import runtime_settings

# Kept for code that imports the old names; the live values come from runtime settings.
OPERATING_HOURS_START = time(9, 0)
OPERATING_HOURS_END = time(17, 0)
OPERATING_HOURS_MESSAGE = "Bookings and events must be scheduled between 9:00 AM and 5:00 PM."


def operating_hours_message() -> str:
    return runtime_settings.operating_hours_message()


def is_within_operating_hours(start: time, end: time) -> bool:
    opens, closes = runtime_settings.operating_hours()
    return start >= opens and end <= closes and end > start
