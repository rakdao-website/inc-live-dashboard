from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ActivityFeed,
    Booking,
    EcosystemMetric,
    Event,
    FaceProfile,
    Visitor,
    Zone,
)

# Demo visitors used by kiosk / face / booking flows.
# Folder names under dataset/ match visitor_phone so import_existing_faces.py
# can enroll photos later.
SEED_VISITORS = [
    {
        "visitor_name": "Aisha Khan",
        "visitor_phone": "+971501234567",
        "visitor_email": "aisha.khan@example.com",
        "license_number": "LIC-1001",
        "visitor_type": "client",
        "company_name": "Aisha Ventures",
        "company_number": "CN-1001",
        "is_existing_client": True,
        "face_consent_given": True,
        "lead_source": "seed",
    },
    {
        "visitor_name": "Omar Hassan",
        "visitor_phone": "+971551112233",
        "visitor_email": "omar.hassan@example.com",
        "license_number": "LIC-1002",
        "visitor_type": "visitor",
        "company_name": None,
        "company_number": None,
        "is_existing_client": False,
        "face_consent_given": True,
        "lead_source": "seed",
    },
    {
        "visitor_name": "Sara Al Maktoum",
        "visitor_phone": "+971529998877",
        "visitor_email": "sara.almaktoum@example.com",
        "license_number": "LIC-1003",
        "visitor_type": "client",
        "company_name": "Desert Labs",
        "company_number": "CN-1003",
        "is_existing_client": True,
        "face_consent_given": True,
        "lead_source": "seed",
    },
    {
        "visitor_name": "James Chen",
        "visitor_phone": "+971504445566",
        "visitor_email": "james.chen@example.com",
        "license_number": None,
        "visitor_type": "visitor",
        "company_name": "Chen Soft",
        "company_number": None,
        "is_existing_client": False,
        "face_consent_given": True,
        "lead_source": "seed",
    },
    {
        "visitor_name": "Fatima Noor",
        "visitor_phone": "+971567778899",
        "visitor_email": "fatima.noor@example.com",
        "license_number": "LIC-1005",
        "visitor_type": "client",
        "company_name": "Noor Media",
        "company_number": "CN-1005",
        "is_existing_client": True,
        "face_consent_given": False,
        "lead_source": "seed",
    },
]


def _seed_zones_and_dashboard(db: Session) -> None:
    if db.scalar(select(Zone.zone_id).limit(1)):
        return

    zones = [
        ("REC_1", "Reception", "reception", False, False),
        ("EVT_1", "Event Area", "event_space", True, False),
        ("TTS_1", "TikTok Studio", "studio", True, False),
        ("POD_1", "Podcast Studio", "studio", True, False),
        ("MR_1", "Meeting Room 1", "meeting_room", True, False),
        ("MR_2", "Meeting Room 2", "meeting_room", True, False),
        ("PAN_1", "Pantry", "amenity", False, False),
        ("ENT_1", "Entrance Area", "entrance", False, False),
        ("BAT_1", "Bathroom", "amenity", False, True),
    ]
    zones += [(f"OFF_{i:02}", f"Office {i}", "office", True, False) for i in range(1, 20)]
    db.add_all(
        Zone(zone_id=a, zone_name=b, zone_type=c, is_bookable=d, is_closed=e)
        for a, b, c, d, e in zones
    )
    db.add(
        EcosystemMetric(
            snapshot_date=date.today(),
            active_companies=2001,
            active_licenses=1202,
            top_sector="Technology",
        )
    )
    today = date.today()
    db.add_all(
        [
            Event(
                zone_id="EVT_1",
                event_name="AI Founders Meetup",
                event_date=today,
                event_time_start=time(11),
                event_time_end=time(12, 30),
                event_organizer="Innovation City",
                event_attendee_count=42,
            ),
            Event(
                zone_id="EVT_1",
                event_name="Web3 Community Hour",
                event_date=today,
                event_time_start=time(15),
                event_time_end=time(16),
                event_organizer="Innovation City",
            ),
        ]
    )
    db.flush()


def seed_visitors(db: Session) -> dict[str, Visitor]:
    """Create demo visitors + face_profiles. Idempotent by phone number."""
    by_phone: dict[str, Visitor] = {}
    for row in SEED_VISITORS:
        phone = row["visitor_phone"]
        existing = db.scalar(select(Visitor).where(Visitor.visitor_phone == phone))
        if existing is not None:
            by_phone[phone] = existing
            continue

        visitor = Visitor(
            visitor_name=row["visitor_name"],
            visitor_phone=phone,
            visitor_email=row["visitor_email"],
            license_number=row["license_number"],
            visitor_type=row["visitor_type"],
            company_name=row["company_name"],
            company_number=row["company_number"],
            is_existing_client=row["is_existing_client"],
            face_consent_given=row["face_consent_given"],
            face_consent_at=datetime.utcnow() if row["face_consent_given"] else None,
            lead_source=row["lead_source"],
        )
        db.add(visitor)
        db.flush()

        if row["face_consent_given"]:
            identifier = f"visitor:{visitor.visitor_id}"
            visitor.face_reference_id = identifier
            db.add(
                FaceProfile(
                    visitor_id=visitor.visitor_id,
                    face_identifier=identifier,
                    consent_given=True,
                )
            )

        by_phone[phone] = visitor

    db.flush()
    return by_phone


def _seed_bookings_and_feed(db: Session, visitors: dict[str, Visitor]) -> None:
    if db.scalar(select(Booking.booking_id).limit(1)):
        return

    today = date.today()
    aisha = visitors.get("+971501234567")
    omar = visitors.get("+971551112233")

    bookings = [
        Booking(
            visitor_id=aisha.visitor_id if aisha else None,
            zone_id="MR_1",
            booking_type="meeting",
            booking_name="Investor Strategy Meeting",
            visitor_name="Aisha Khan",
            visitor_phone="+971501234567",
            visitor_email="aisha.khan@example.com",
            visitor_is_client=True,
            booking_start_date=today,
            booking_end_date=today,
            booking_date=today,
            booking_time_start=time(11),
            booking_time_end=time(12),
        ),
        Booking(
            visitor_id=omar.visitor_id if omar else None,
            zone_id="POD_1",
            booking_type="studio",
            booking_name="Founder Stories Podcast",
            visitor_name="Omar Hassan",
            visitor_phone="+971551112233",
            visitor_email="omar.hassan@example.com",
            visitor_is_client=False,
            booking_start_date=today,
            booking_end_date=today,
            booking_date=today,
            booking_time_start=time(10, 30),
            booking_time_end=time(12, 30),
        ),
    ]
    db.add_all(bookings)
    db.flush()

    db.add_all(
        [
            ActivityFeed(
                feed_id="feed_001",
                booking_id=bookings[0].booking_id,
                activity_action="occupied",
                category="room",
            ),
            ActivityFeed(
                feed_id="feed_002",
                event_id=1,
                activity_action="starts_now",
                category="event",
            ),
            ActivityFeed(
                feed_id="feed_003",
                booking_id=bookings[1].booking_id,
                activity_action="occupied",
                category="studio",
            ),
            ActivityFeed(
                feed_id="feed_004",
                activity_action="license_application_submitted",
                category="company",
            ),
        ]
    )


def seed_sample_data(db: Session) -> None:
    """Seed zones/events/visitors/bookings for the POC.

    Face embeddings are NOT invented here — drop real photos into dataset/
    and run scripts/import_existing_faces.py.
    """
    _seed_zones_and_dashboard(db)
    visitors = seed_visitors(db)
    _seed_bookings_and_feed(db, visitors)
    db.commit()
