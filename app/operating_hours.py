from datetime import time


OPERATING_HOURS_START = time(9, 0)
OPERATING_HOURS_END = time(17, 0)
OPERATING_HOURS_MESSAGE = "Bookings and events must be scheduled between 9:00 AM and 5:00 PM."


def is_within_operating_hours(start: time, end: time) -> bool:
    return start >= OPERATING_HOURS_START and end <= OPERATING_HOURS_END and end > start
