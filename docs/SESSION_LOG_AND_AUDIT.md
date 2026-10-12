# Conversation logs, customer list and audit trail

Apply `migrations/2026_10_12_add_session_log_masking_audit_chain.sql` once, then restart the backend.

## Conversation logs (transcripts)
- The kiosk voice assistant reports each conversation to `POST /api/kiosk/sessions` (start), `/{id}/messages` and `/{id}/end`.
- Stored in `kiosk_sessions` and `kiosk_session_messages`. **Emails and phone numbers are masked before saving**; the real
  values never reach the log. The visitor's name comes from our database, not from the browser.
- Settings (admin → Settings → Conversation logs): `sessions.store_transcripts` (on/off) and `sessions.retention_days`
  (default 90). Expired logs are deleted automatically when a new conversation starts.
- Staff read them under **Conversation logs** (roles: super user, reviewer). Opening the list or a transcript is audited.

## Customer list
- **Customers** (roles: all four) shows name, type, company and the **masked** email and phone, never the real ones.
- Masked copies are stored in `visitors.email_masked` / `phone_masked` and kept in step automatically.
  Format: `m*****@e*****.com`, `+971*****67`.

## One customer, many visits
- A person is one row in **Customers** however often they come. The list shows **Visits** (kiosk check-ins) and
  **Conversations**, and can be sorted by name, most recent visit or most visits; search by name or company.
- Click a name for their history: every visit (newest first, with how they were recognised and what they asked for) and
  every logged conversation, each opening its transcript. "Open in conversation logs" filters that page to this one customer.

## Audit trail (super user)
- Every change, sign-in event and every **view** of customers or transcripts is recorded, with a type:
  Sign-in, Viewed data, Changes, Privacy, System.
- **Tamper evident:** each row stores a hash of its content plus the previous row's hash. **Check integrity** in the
  admin walks the chain and reports the first altered or missing row. On PostgreSQL a trigger also refuses UPDATE and
  DELETE on `admin_audit_log`. The audit log is never auto-deleted.
- **Export CSV** (filtered, up to 5000 rows); the export is itself recorded.
- Rows written before this change have no hash and are reported as "older entries".
