# Screen Frontend Backend Integration Design

## Goal

Link the screen frontend to the live backend and database so map status, events, bookings, metrics, and screen-created bookings use the same source of truth as the kiosk and admin dashboard.

## Approved Approach

Use the existing public backend `/api/*` live-data routes for reads and add one small public screen-booking endpoint for writes. The screen frontend will call the backend directly at `http://127.0.0.1:8000`, with CORS enabled for local screen/admin/kiosk frontend ports.

## Data Flow

- Screen reads live data from `/api/header`, `/api/zones`, `/api/activity-metrics`, `/api/ecosystem-metrics`, `/api/events`, `/api/bookings`, and `/api/activity-feed`.
- Screen map room status is derived from backend zones/bookings, not local-only mock state.
- Screen booking popup submits a real booking to the backend, which writes to the `bookings` table and upserts/fetches a visitor by phone.
- New screen bookings use `lead_source="map_screen"` for visitor records and create visitor activity with `selected_service="screen_booking"` so admin activity can distinguish map-screen interactions.
- Existing database constraints and backend validation reject closed zones, non-bookable zones, overlapping bookings, invalid times, and out-of-hours requests.

## Error Handling

- Frontend API calls return readable errors from backend JSON envelopes.
- Booking modal shows a submission error without closing the modal.
- Successful booking refreshes dashboard data immediately and then returns to polling.

## Testing

- Backend tests cover screen booking creation, overlap rejection, invalid zone rejection, and CORS.
- Frontend TypeScript compilation verifies API request types and booking form changes.
