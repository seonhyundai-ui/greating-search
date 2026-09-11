from __future__ import annotations

import re


EMAIL_RE = re.compile(
    r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"^(?:\+?82[- ]?)?0?1[016789][- ]?\d{3,4}[- ]?\d{4}$"
)
RESIDENT_RE = re.compile(r"^\d{6}[- ]?[1-4]\d{6}$")
LONG_DIGIT_RE = re.compile(r"^\d{8,}$")

UNUSABLE_TERMS = {
    "",
    "(not set)",
    "(blank)",
    "not set",
    "null",
    "none",
}


def normalize_search_term(value: object) -> str:
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def is_probable_pii(term: str) -> bool:
    compact = term.strip()

    return bool(
        EMAIL_RE.fullmatch(compact)
        or PHONE_RE.fullmatch(compact)
        or RESIDENT_RE.fullmatch(compact)
        or LONG_DIGIT_RE.fullmatch(compact)
    )


def is_safe_search_term(value: object) -> bool:
    term = normalize_search_term(value)

    if term.lower() in UNUSABLE_TERMS:
        return False

    if is_probable_pii(term):
        return False

    return True
