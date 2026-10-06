"""Admin panel backend: sessions, roles, audit log and the panel's own endpoints.

Everything the admin panel adds lives in this package. The older routers
(`app/admin.py`, `app/routers/face.py`) stay where they are and are protected by
the same gate (`deps.admin_gate`) when they are included in `app/main.py`.
"""
