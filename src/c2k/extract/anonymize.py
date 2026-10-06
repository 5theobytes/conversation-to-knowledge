"""Deterministic volatile-data scrubber.

Replaces values that must never land in a knowledge base with typed
placeholders and reports which kinds were substituted. In the original
project this scrubbing was demanded from the LLM worker AND re-checked by the
rule engine; here the deterministic scrubber is the first line and the rule
``reject_pii_leak`` is the backstop.

Kinds: phone, card, amount, date, time, email, name (via a caller-supplied
blocklist; the mock pipeline passes the known participant names).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2,4}(?!\w)")
CARD_RE = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}(?:[\s\-]\d{4})?\b")
LONG_DIGITS_RE = re.compile(r"\b\d{8,}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
AMOUNT_RE = re.compile(
    r"(?:\b\d[\d.,]{0,10}(?:\s\d{3})*\s*(?:usd|eur|gbp|rub|\u0440\u0443\u0431\.?|\u0440\u0443\u0431\u043b\u0435\u0439|\$|€|£)(?!\w))|(?:(?:\$|€|£)\s*\d[\d.,]{0,10})",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")

PLACEHOLDER_RE = re.compile(r"<[a-z_]+>")


@dataclass
class ScrubResult:
    text: str
    kinds: list[str] = field(default_factory=list)


def scrub(text: str, names: list[str] | None = None, keep_time: bool = False) -> ScrubResult:
    kinds: list[str] = []
    t = text or ""

    def sub(rx: re.Pattern[str], placeholder: str, kind: str) -> None:
        nonlocal t
        new = rx.sub(placeholder, t)
        if new != t:
            kinds.append(kind)
            t = new

    sub(EMAIL_RE, "<email>", "email")
    sub(CARD_RE, "<card_number>", "card")
    sub(AMOUNT_RE, "<amount>", "amount")
    sub(DATE_RE, "<date>", "date")
    if not keep_time:
        sub(TIME_RE, "<time>", "time")
    sub(PHONE_RE, "<phone_number>", "phone")
    sub(LONG_DIGITS_RE, "<id_number>", "id")
    for n in names or []:
        for part in {n, n.split()[0]}:
            if len(part) < 3:
                continue
            rx = re.compile(r"(?<!\w)" + re.escape(part) + r"(?!\w)", re.IGNORECASE)
            new = rx.sub("<person_name>", t)
            if new != t:
                kinds.append("name")
                t = new
    t = re.sub(r"\s{2,}", " ", t).strip()
    return ScrubResult(t, sorted(set(kinds)))


def has_raw_volatile(text: str, names: list[str] | None = None) -> list[str]:
    """Return the list of volatile kinds still present verbatim (backstop check)."""
    found: list[str] = []
    t = PLACEHOLDER_RE.sub(" ", text or "")
    if EMAIL_RE.search(t):
        found.append("email")
    if CARD_RE.search(t):
        found.append("card")
    if AMOUNT_RE.search(t):
        found.append("amount")
    if DATE_RE.search(t):
        found.append("date")
    if LONG_DIGITS_RE.search(t):
        found.append("id")
    for n in names or []:
        if re.search(r"(?<!\w)" + re.escape(n.split()[0]) + r"(?!\w)", t, re.IGNORECASE):
            found.append("name")
            break
    return found
