"""Spacebring REST API client (Basic auth).

Covers the seven calls the kiosk needs: list rooms, check availability,
create / list / get / update / cancel bookings. Spacebring allows 10 requests
per second per account, so calls are throttled and a 429 is retried with
backoff.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import httpx

from app.config import settings

MAX_REQUESTS_PER_SECOND = 8  # stay under Spacebring's 10 req/s limit
MAX_RETRIES_ON_429 = 3
REQUEST_TIMEOUT_SECONDS = 15.0


class SpacebringError(Exception):
    """A Spacebring call failed (HTTP error, validation error or network)."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SpacebringNotConfigured(SpacebringError):
    pass


def to_spacebring_datetime(value: datetime) -> str:
    """Spacebring expects ISO-8601 UTC instants like 2026-11-15T06:00:00.000Z."""
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


class _RateLimiter:
    def __init__(self, per_second: int):
        self._interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


class SpacebringClient:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        network_id: str = "",
        location_id: str = "",
        transport: httpx.BaseTransport | None = None,
    ):
        if not client_id or not client_secret:
            raise SpacebringNotConfigured("Spacebring credentials are not configured")
        headers = {"spacebring-network-id": network_id} if network_id else {}
        self.location_id = location_id
        self._limiter = _RateLimiter(MAX_REQUESTS_PER_SECOND)
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(client_id, client_secret),
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        attempt = 0
        while True:
            self._limiter.wait()
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise SpacebringError(f"Spacebring request failed: {exc}") from exc

            if response.status_code == 429 and attempt < MAX_RETRIES_ON_429:
                attempt += 1
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            if response.status_code >= 400:
                code = message = None
                try:
                    body = response.json()
                    code, message = body.get("code"), body.get("message")
                except ValueError:
                    pass
                raise SpacebringError(
                    message or f"Spacebring returned HTTP {response.status_code}",
                    status_code=response.status_code,
                    code=code,
                )

            if response.status_code == 204 or not response.content:
                return {}
            return response.json()

    # --- rooms -----------------------------------------------------------
    def list_rooms(self, location_id: str | None = None) -> list[dict[str, Any]]:
        rooms: list[dict[str, Any]] = []
        params: dict[str, Any] = {"locationRef": location_id or self.location_id, "limit": 100}
        while True:
            data = self._request("GET", "/resources/v1", params=params)
            rooms.extend(data.get("resources", []))
            token = data.get("nextPageToken")
            if not token:
                return rooms
            params = {**params, "nextPageToken": token}

    def check_availability(self, resource_id: str, start: datetime, end: datetime) -> dict[str, Any]:
        """Returns {"available": bool, "reason": {...}?}."""
        return self._request(
            "POST",
            f"/resources/v1/{resource_id}/availability",
            json={"startDate": to_spacebring_datetime(start), "endDate": to_spacebring_datetime(end)},
        )

    # --- customers ---------------------------------------------------------
    def find_memberships(
        self,
        *,
        email: str,
        company_id: str | None = None,
        location_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Memberships (customers) with this user email, optionally within one company."""
        params: dict[str, Any] = {
            "locationRef": location_id or self.location_id,
            "userEmail": email,
            "limit": 100,
        }
        if company_id:
            params["companyRef"] = company_id
        return self._request("GET", "/community/memberships/v1", params=params).get("memberships", [])

    # --- bookings --------------------------------------------------------
    def create_booking(
        self,
        *,
        resource_id: str,
        start: datetime,
        end: datetime,
        title: str,
        owner_customer_id: str | None = None,
        send_updates: str = "none",
    ) -> dict[str, Any]:
        booking: dict[str, Any] = {
            "resourceRef": resource_id,
            "startDate": to_spacebring_datetime(start),
            "endDate": to_spacebring_datetime(end),
            "title": title,
            "sendUpdates": send_updates,
        }
        if owner_customer_id:
            booking["membershipRefOwner"] = owner_customer_id
        return self._request("POST", "/resources/bookings/v1", json={"booking": booking})["booking"]

    def get_booking(self, booking_id: str) -> dict[str, Any]:
        return self._request("GET", f"/resources/bookings/v1/{booking_id}")["booking"]

    def list_bookings(
        self,
        *,
        location_id: str | None = None,
        resource_id: str | None = None,
        owner_customer_id: str | None = None,
        starts_from: datetime | None = None,
        status: str | None = None,
        limit: int = 100,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """All matching bookings, following pagination (oldest start first)."""
        params: dict[str, Any] = {
            "locationRef": location_id or self.location_id,
            "limit": min(limit, 100),
            "order": "startDate:asc",
        }
        if resource_id:
            params["resourceRef"] = resource_id
        if owner_customer_id:
            params["membershipRefOwner"] = owner_customer_id
        if starts_from is not None:
            params["startDate[gte]"] = to_spacebring_datetime(starts_from)
        if status:
            params["status"] = status

        bookings: list[dict[str, Any]] = []
        for _ in range(max_pages):
            data = self._request("GET", "/resources/bookings/v1", params=params)
            bookings.extend(data.get("bookings", []))
            token = data.get("nextPageToken")
            if not token:
                return bookings
            params = {**params, "nextPageToken": token}
        raise SpacebringError("Too many pages of bookings; narrow the window")

    def update_booking(
        self,
        booking_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        title: str | None = None,
        send_updates: str = "none",
    ) -> dict[str, Any]:
        booking: dict[str, Any] = {"sendUpdates": send_updates}
        if start is not None:
            booking["startDate"] = to_spacebring_datetime(start)
        if end is not None:
            booking["endDate"] = to_spacebring_datetime(end)
        if title is not None:
            booking["title"] = title
        return self._request("PATCH", f"/resources/bookings/v1/{booking_id}", json={"booking": booking})["booking"]

    def cancel_booking(self, booking_id: str) -> None:
        self._request("DELETE", f"/resources/bookings/v1/{booking_id}")


def spacebring_enabled() -> bool:
    return bool(settings.spacebring_client_id and settings.spacebring_client_secret)


@lru_cache
def get_spacebring_client() -> SpacebringClient:
    return SpacebringClient(
        base_url=settings.spacebring_base_url,
        client_id=settings.spacebring_client_id,
        client_secret=settings.spacebring_client_secret,
        network_id=settings.spacebring_network_id,
        location_id=settings.spacebring_location_id,
    )
