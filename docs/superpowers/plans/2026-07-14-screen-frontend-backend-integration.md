# Screen Frontend Backend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the screen frontend to live backend/database reads and real map-screen booking writes.

**Architecture:** The backend keeps existing `/api/*` read routes and adds `POST /api/screen/bookings` for public screen booking. The screen frontend calls `http://127.0.0.1:8000` directly, polls live data, submits bookings, refreshes after success, and surfaces backend JSON errors.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Next.js, React, TypeScript.

## Global Constraints

- Use existing database tables: `zones`, `bookings`, `visitors`, and `visitor_activity`.
- Save screen-created visitor source as `map_screen`.
- Reuse operating-hours and overlap rules.
- Keep the screen UI visually intact; change behavior and data wiring only.

---

### Task 1: Backend Screen Booking Endpoint

**Files:**
- Modify: `app/kiosk_schemas.py`
- Modify: `app/routers/kiosk.py`
- Test: `tests/test_screen_booking_api.py`

**Interfaces:**
- Consumes: `ScreenBookingCreate`
- Produces: `POST /api/screen/bookings`

- [ ] Write failing backend tests for successful booking and conflict handling.
- [ ] Add `ScreenBookingCreate` with visitor details, zone ID, date, start time, and end time.
- [ ] Implement public booking creation with zone validation, visitor upsert using `lead_source="map_screen"`, overlap handling, and JSON response.
- [ ] Run focused backend tests.

### Task 2: Screen Frontend API Wiring

**Files:**
- Modify: `components/screen/ScreenDashboard.tsx`

**Interfaces:**
- Consumes: `POST /api/screen/bookings`
- Produces: real booking modal submit and refreshed dashboard state.

- [ ] Change API base default to `http://127.0.0.1:8000`.
- [ ] Replace local-only booking completion with POST to the backend.
- [ ] Map room IDs to real zone IDs: `meetingroom1 -> MR_1`, `meetingroom2 -> MR_2`, `podcast -> POD_1`, `tiktokstudio -> TTS_1`.
- [ ] Show booking submission errors in the modal.
- [ ] Refresh live data after successful booking.

### Task 3: Verification

**Files:**
- Test backend and screen frontend.

- [ ] Run `python -m pytest -q`.
- [ ] Run `npx.cmd tsc --noEmit` in the screen frontend.
- [ ] Restart backend and screen frontend.
- [ ] Verify health endpoints and live CORS.
