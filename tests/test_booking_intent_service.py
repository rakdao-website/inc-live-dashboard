import asyncio
from unittest.mock import patch

from app.booking_intent_service import parse_booking_intent


def test_parse_booking_intent_uses_service_defaults_when_room_is_not_spoken():
    rooms = [
        {
            "zone_id": "POD_1",
            "zone_name": "Podcast Studio",
            "zone_type": "studio",
            "status": "available",
            "details": {},
        }
    ]

    with patch("app.booking_intent_service.build_room_directory", return_value=rooms), patch(
        "app.booking_intent_service.find_room_in_question", return_value=None
    ):
        result = asyncio.run(
            parse_booking_intent(
                None,
                "Book the podcast studio tomorrow at 3 pm",
                service_type="podcast_studio",
            )
        )

    assert result.zone_id == "POD_1"
    assert result.zone_name == "Podcast Studio"
    assert result.duration_minutes is None
    assert "duration" in result.missing


def test_parse_booking_intent_extracts_time_and_service_defaults_from_natural_speech():
    with patch("app.booking_intent_service.build_room_directory", return_value=[]), patch(
        "app.booking_intent_service.find_room_in_question", return_value=None
    ):
        result = asyncio.run(
            parse_booking_intent(
                None,
                "Book a room tomorrow 3 pm for one hour",
                service_type="meeting_room",
            )
        )

    assert result.zone_id == "MR_1"
    assert result.zone_name == "Meeting Room 1"
    assert result.booking_date is not None
    assert result.booking_time_start is not None
    assert result.duration_minutes == 60
    assert "date" not in result.missing
    assert "time" not in result.missing
    assert "duration" not in result.missing
