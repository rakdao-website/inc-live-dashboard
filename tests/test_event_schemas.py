from datetime import date, time

from app.schemas import EventCreate


def test_event_create_defaults_to_event_area_zone_when_zone_is_omitted():
    event = EventCreate(
        event_name="Interns",
        event_date=date(2026, 7, 7),
        event_time_start=time(13, 46),
        event_time_end=time(14, 16),
        event_organizer="events",
        event_attendee_count=5,
    )

    assert event.zone_id == "EVT_1"
    assert event.event_location == "Event Area"


def test_event_create_defaults_blank_location_to_event_area():
    event = EventCreate(
        zone_id="EVT_1",
        event_name="Interns",
        event_date=date(2026, 7, 7),
        event_time_start=time(13, 46),
        event_time_end=time(14, 16),
        event_location="",
        event_organizer="events",
        event_attendee_count=5,
    )

    assert event.event_location == "Event Area"
