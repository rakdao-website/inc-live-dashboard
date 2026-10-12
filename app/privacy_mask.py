"""Masking of contact details for screens and logs that do not need the real value.

mask_email("mohamad@example.com") -> "m*****@e*****.com"
mask_phone("+971 50 123 4567")    -> "+971*****67"
mask_text(...) masks every email address and phone number found inside free text, which is how
conversation transcripts are stored: the real contact details never reach the log.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A phone number: optional +, then 8 to 15 digits that may be split by spaces, dots, dashes or brackets.
_PHONE = re.compile(r"(?<![\w])\+?\d(?:[\s().\-]?\d){7,14}(?![\w])")


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.strip().rpartition("@")
    if not local or "." not in domain:
        return None
    name, _, tld = domain.rpartition(".")
    return f"{local[0]}*****@{name[:1] or '*'}*****.{tld}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 6:
        return None
    prefix = "+" if phone.strip().startswith("+") else ""
    return f"{prefix}{digits[:3]}*****{digits[-2:]}"


def mask_text(text: str) -> str:
    """Hide emails and phone numbers in a sentence, keeping the rest readable."""
    text = _EMAIL.sub(lambda m: mask_email(m.group(0)) or "[email]", text)
    return _PHONE.sub(lambda m: mask_phone(m.group(0)) or "[phone]", text)
