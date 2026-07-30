# Frontend API smoke tester

Open this from the running backend (recommended):

```text
http://127.0.0.1:8000/fe-test/
```

## What it tests

1. **Camera + face** — open webcam → snap → `POST /api/face/detect`
2. **Unknown captures** — list / get / web-search / link / dismiss
3. **Voice** — browser mic (or type) → `POST /api/kiosk/room-question` → speak via `/api/kiosk/speak` or browser TTS
4. **Lookup / visit / book** — seed visitor Aisha → visit session → booking
5. **Dashboard** — zones, bookings, events, header, activity feed

## Requirements

- Backend running on port 8000
- Chrome/Edge for speech recognition + camera
- Allow camera / mic permissions
- Face embeddings imported if you want a known match (`scripts/import_existing_faces.py`)
