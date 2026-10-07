# Live dashboard metrics API

One endpoint with every number the live dashboard display needs.

```
GET /api/dashboard/metrics
```

Base URL is the backend, for example `http://127.0.0.1:8000`.

- **Counts only.** No visitor names, phone numbers or emails, and not even room or event names.
- **Public and read-only.** No sign-in.
- **Live.** Calculated on every call, in Dubai time, from the zones, bookings, events and kiosk
  check-ins. Bookings include the copies of Spacebring bookings. The response is sent with
  `Cache-Control: no-store`.
- **Poll every 10 to 30 seconds.** `as_of` says when the numbers were calculated.
- **CORS.** The display's address must be in `CORS_ALLOWED_ORIGINS` (backend `.env`), for example
  `http://localhost:3004`. Otherwise the browser blocks the calls.

## The tiles

| Tile | Field |
|---|---|
| Meetings Active | `meetings_active` |
| Rooms Occupied `x / y` | `rooms_occupied` / `rooms_total` |
| Events Today | `events_today` |
| Events happening now | `events_live` |
| Bookings today | `bookings_today` |
| Visitors today | `visitors_today` |
| Active companies | `ecosystem.active_companies` |
| Active licences | `ecosystem.active_licenses` |

## Response

```json
{
  "as_of": "2026-10-07T12:59:35.990776",
  "timezone": "Asia/Dubai",
  "meetings_active": 1,
  "rooms_occupied": 3,
  "rooms_total": 28,
  "rooms_closed": 0,
  "events_today": 2,
  "events_live": 1,
  "bookings_today": 5,
  "visitors_today": 14,
  "rooms_by_type": {
    "meeting_room": { "total": 2,  "occupied": 1 },
    "studio":       { "total": 6,  "occupied": 2 },
    "office":       { "total": 19, "occupied": 0 },
    "event_space":  { "total": 1,  "occupied": 0 }
  },
  "ecosystem": { "snapshot_date": "2026-10-05", "active_companies": 2001, "active_licenses": 1202 }
}
```

## Definitions

- `rooms_total`: bookable rooms that are open. Rooms switched off by staff are counted in `rooms_closed`, not here.
- `rooms_occupied`: those rooms with a booking or an event happening right now.
- `meetings_active`: meeting rooms in use right now (a booking or an event).
- `events_today`: all events dated today. `events_live`: those happening now.
- `bookings_today`: bookings dated today.
- `visitors_today`: different people who checked in at the kiosk today (each person counted once).
- `rooms_by_type`: the same total and occupied counts per room type, for a breakdown tile.
- `ecosystem`: the latest company and licence counts recorded by staff. It is `null` if none were recorded.

## Example

```ts
const res = await fetch(`${API}/api/dashboard/metrics`, { cache: "no-store" });
const m = await res.json();
// m.meetings_active, `${m.rooms_occupied} / ${m.rooms_total}`, m.events_today
```

```bash
curl -s http://127.0.0.1:8000/api/dashboard/metrics
```

## Older endpoints (still there, not for the display)

- `GET /api/activity-metrics` returns similar numbers, but `zones_total` also counts rooms that are
  closed and `visitors_count` adds event attendees to bookings. Use `/api/dashboard/metrics` instead.
- **Do not use `GET /api/bookings` on a public screen.** It returns the visitor's name, phone number
  and email to anyone, with no sign-in.
