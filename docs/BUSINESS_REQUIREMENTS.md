# Visitor Experience — Business Requirements (Draft v0.5)

**Date:** 29 Sep 2026 · **Scope:** Proof of concept (POC) · **Status:** For review
**Changes since v0.4 (3 Oct 2026):** pgvector replaces Qdrant; room booking goes through Spacebring (sandbox) for the podcast room and all five TikTok rooms. Meeting rooms stay internal.

---

## 1. Goal

Recognise people as they arrive at Innovation City, prepare who they might be **before** they reach the screen, and let them confirm and continue by voice.

## 2. POC scope

| In scope | Out of scope for the POC |
|---|---|
| **Entrance camera** outside the main door: logs arrivals only, no greeting | Business centre and packages screen |
| **Screen 2** with its own camera, microphone and speaker | Screen 1 and its separate kiosk flow |
| Face recognition, web search, "Is this you?", registration, voice assistant | Live floor tracking and heatmaps |
| Voice booking, including **podcast and TikTok room booking through Spacebring** | |
| Staff review of unidentified faces | Live dashboard UI |

## 3. The journey

1. **Outside the door.** The entrance camera sees a person. It only logs the arrival. **No greeting.**
   - **Known person:** log "known visitor arrived".
   - **Unknown person:** save the face and search the web for likely matches in the background.
2. **At Screen 2.** By the time the person walks to the screen, the web results are usually ready. Camera 2 scans their face.
   - **Known:** greet by name and start the voice assistant.
   - **Unknown:** match them to their entrance capture, then show **"Is this you?"** with the top 3 photos. They pick one or choose "none of these".
3. **New person.** The voice assistant collects name, phone, email and visitor type. The form fills in on screen as they speak. They give consent and their face is saved.
4. **Admin approval.** The new entry, or the link to a chosen web suggestion, is saved as **Pending** until an admin approves it in the admin panel.
5. **Help.** The voice assistant answers questions and makes bookings. Podcast and TikTok room bookings go to Spacebring.
6. **Record.** The visit is logged, linked to the entrance arrival.

## 4. Requirements

Priority: **M** = must have, **S** = should have.

### 4.1 Entrance camera

| ID | Requirement | Pri |
|---|---|---|
| E1 | Detect faces at the door and log each arrival (time, known or unknown) | M |
| E2 | Never greet or display anything at the entrance | M |
| E3 | Count the same person once per visit, not once per video frame | M |
| E4 | For unknown faces, run the web search automatically and save up to 3 results | M |
| E5 | Search everyone unknown who is seen at the entrance (premises are private property), but only once per person per visit, with a daily cap to control cost | M |

### 4.2 Screen 2 — recognition and confirmation

| ID | Requirement | Pri |
|---|---|---|
| R1 | Recognise returning people by face without any input | M |
| R2 | Link a face at Screen 2 to its earlier entrance capture, so the ready web results appear immediately | M |
| R3 | Show up to 3 candidate **photos** with "Is this you?". Source links are **not** shown to the visitor, staff only | M |
| R4 | A web match is never accepted without the visitor's confirmation. The visitor either selects a suggestion or creates a new entry if none is them | M |
| R4a | Any selection or new entry is held **pending admin approval** before it becomes a confirmed record (new records start as **Pending**; approval rules such as who and how fast come later) | M |
| R5 | Fall back to phone number if the face cannot be used | M |
| R6 | If web search is slow or fails, continue straight to registration with no error shown | M |

### 4.3 Registration and consent

| ID | Requirement | Pri |
|---|---|---|
| R7 | Register new people by voice or touch: name, phone, email, visitor type, company if relevant | M |
| R8 | Save a face profile only with explicit consent, with the time recorded | M |
| R9 | Post a visible notice at the entrance and Screen 2 that faces are scanned and searched | M |
| R10 | A visitor can decline face saving and still use the assistant | S |

### 4.4 Voice assistant (Screen 2 microphone and speaker)

| ID | Requirement | Pri |
|---|---|---|
| V1 | Talk naturally in real time, and cope with background noise (echo-cancelling mic and speaker) | M |
| V2 | Answer questions about rooms and services from an editable knowledge document | M |
| V3 | Register people, look them up by phone, and book rooms by conversation | M |
| V4 | Room availability always comes from live booking data | M |
| V5 | Book, move and cancel the **podcast room and TikTok rooms through the Spacebring API**, by voice, and confirm the result to the visitor *(done, sandbox)* | M |
| V6 | Meeting rooms are booked as today (internal), unless told otherwise | S |

### 4.5 Records and staff review

| ID | Requirement | Pri |
|---|---|---|
| S1 | Record every arrival and visit, including how the person was recognised | M |
| S2 | Flag returning visitors and remember their last visit | M |
| S3 | Staff can review unidentified faces, see the web source links, link to a visitor, dismiss, or re-run the search | M |
| S4 | Admin approval queue: approve or reject pending visitor entries and face links, with who and when recorded | M |

## 5. Data ownership and storage

**Ownership:** the data is owned and held by Innovation City. Owning it does not remove the legal duties under UAE PDPL, so a named person must still sign off (see Decisions).

**Done (3 Oct 2026):** face vectors moved (photos as files and retention are still to do). Original recommendation: move face vectors into the existing PostgreSQL database using the **pgvector** extension, replacing the separate Qdrant server.

| | Today | Recommended |
|---|---|---|
| Face vectors | ~~Qdrant (separate server)~~ moved | **pgvector** column in PostgreSQL (`face_vectors`) |
| Face photos | Base64 text inside database rows and Qdrant | **Encrypted image files** (or private storage); the database keeps only the file path |
| Web results | Base64 thumbnails in the database | Keep, but auto-delete after a retention period |
| Deleting a person | Must be done in two systems | **One delete**, so erasure requests are simple |

**Why:** the POC has hundreds to a few thousand faces, which pgvector handles easily. One database means one backup, one access policy and one place to enforce retention. Base64 photos bloat rows and are harder to protect than files. The change touches one module (`face_recognition_service.py`).

**Retention:** the target for unidentified faces and web results is **90 days**. For the POC nothing is deleted automatically. Every record gets an expiry date so deletion can be switched on later. Consented profiles are kept until the person asks to be removed.

## 6. Known issues to fix first

1. **The "top 3 web matches" step does not work today.** A code error makes unknown visitors skip it silently. It's a one-line fix.
2. **Entrance camera and linking are not built.** R2 (matching a Screen 2 face to its entrance capture) is new work.
3. **Approval queue is new.** Today a confirmed match is enrolled immediately, with no admin step (R4a, S4).
4. **Spacebring is connected to the sandbox only.** Production needs the live credentials and a zone re-link. Bookings are anonymous (no credits) until customer matching is decided.
5. **Default admin login** (`admin` / `admin123`) must be replaced. It now protects the approval queue.

## 7. Success measures

| Measure | Target |
|---|---|
| Returning visitors recognised without typing anything | ≥ 90% |
| Time from arrival to service chosen | < 60 seconds for known visitors |
| New visitor registration completed | < 2 minutes |
| Visitors needing reception help | Falling month on month |

## 8. Decisions

**Confirmed**

| Topic | Decision |
|---|---|
| Entrance camera | Logs only, no greeting, starts web search for unknown faces |
| Web searches on passers-by | Allowed, premises are private property |
| Retention | 90 days target, no automatic deletion for the POC |
| Storage | pgvector in PostgreSQL (done), photos as files (to do) |
| Voice booking | In scope |
| TikTok rooms and podcast room | Booked through Spacebring (sandbox working; five TikTok rooms and the podcast room) |
| Meeting rooms | Stay on our own booking system. Moving them to Spacebring is a possible later phase (they do not exist in Spacebring yet) |
| Face match sign-off | Visitor selects a suggestion or creates a new entry. It stays **Pending** until an admin approves it |
| Approval and face-data management | Done in our built-in admin panel |

**Deferred to a later phase**

- Approval rules: who approves, how fast, and whether a pending visitor can continue as a guest.
- Automatic deletion after 90 days.
- Moving meeting rooms to Spacebring.

**Assumptions to check**

1. Spacebring is the master calendar for the podcast and TikTok rooms, so availability is read from Spacebring and not from our database.
2. Until the approval rules are set, a pending visitor can still use the voice assistant.
3. The signage wording at the entrance and Screen 2 is written by us and approved through the same admin process.
