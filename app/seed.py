from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityFeed, Booking, EcosystemMetric, Event, Zone


def seed_sample_data(db: Session) -> None:
    if db.scalar(select(Zone.zone_id).limit(1)):
        return
    zones = [
        ("REC_1", "Reception", "reception", False, False), ("EVT_1", "Event Area", "event_space", True, False),
        ("TTS_1", "TikTok Studio", "studio", True, False), ("POD_1", "Podcast Studio", "studio", True, False),
        ("MR_1", "Meeting Room 1", "meeting_room", True, False), ("MR_2", "Meeting Room 2", "meeting_room", True, False),
        ("PAN_1", "Pantry", "amenity", False, False), ("ENT_1", "Entrance Area", "entrance", False, False), ("BAT_1", "Bathroom", "amenity", False, True),
    ]
    zones += [(f"OFF_{i:02}", f"Office {i}", "office", True, False) for i in range(1, 20)]
    db.add_all(Zone(zone_id=a, zone_name=b, zone_type=c, is_bookable=d, is_closed=e) for a, b, c, d, e in zones)
    db.add(EcosystemMetric(snapshot_date=date.today(), active_companies=2001, active_licenses=1202))
    today = date.today()
    db.add_all([
        Event(zone_id="EVT_1", event_name="AI Founders Meetup", event_date=today, event_time_start=time(11), event_time_end=time(12,30), event_organizer="Innovation City", event_attendee_count=42),
        Event(zone_id="EVT_1", event_name="Web3 Community Hour", event_date=today, event_time_start=time(15), event_time_end=time(16), event_organizer="Innovation City"),
        Booking(zone_id="MR_1", booking_type="meeting", booking_name="Investor Strategy Meeting", visitor_name="Aisha Khan", visitor_phone="+971501234567", visitor_email="aisha.khan@example.com", visitor_is_client=True, booking_start_date=today, booking_end_date=today, booking_date=today, booking_time_start=time(11), booking_time_end=time(12)),
        Booking(zone_id="POD_1", booking_type="studio", booking_name="Founder Stories Podcast", visitor_name="Omar Hassan", visitor_phone="+971551112233", visitor_email="omar.hassan@example.com", visitor_is_client=False, booking_start_date=today, booking_end_date=today, booking_date=today, booking_time_start=time(10,30), booking_time_end=time(12,30)),
    ])
    db.flush()
    db.add_all([
        ActivityFeed(feed_id="feed_001", booking_id=1, activity_action="occupied", category="room"),
        ActivityFeed(feed_id="feed_002", event_id=1, activity_action="starts_now", category="event"),
        ActivityFeed(feed_id="feed_003", booking_id=2, activity_action="occupied", category="studio"),
        ActivityFeed(feed_id="feed_004", activity_action="license_application_submitted", category="company"),
    ])
    db.commit()
