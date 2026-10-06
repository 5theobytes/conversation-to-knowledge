"""Language and chatter detection (deterministic, regex-based).

Script-based detection is the honest baseline: Thai and Cyrillic scripts are
unambiguous; everything else falls back to ``en``. Marker lists for other
Latin-script languages can be added to ``LATIN_MARKERS``.
"""
from __future__ import annotations

import re

THAI_RE = re.compile(r"[฀-๿]")
CYR_RE = re.compile(r"[\u0400-\u04ff]")
LATIN_MARKERS: dict[str, re.Pattern[str]] = {
    # language code -> regex of frequent function words / colloquial markers
}

# Short acknowledgements / thanks across en / ru / th. Whole-message match.
ACK_PAT = re.compile(
    r"^(?:[\W_]*"
    r"(ok|okey|okay|noted|copy|got\s*it|"
    r"thanks?|thank\s*you|thx|ty|"
    r"\u0441\u043f\u0430\u0441\u0438\u0431[\u043e\u0430]|\u043f\u0430\u0441\u0438\u0431|\u043e\u043a|\u043e\u043a\u0435\u0439|\u0445\u043e\u0440\u043e\u0448\u043e|\u043f\u043e\u043d\u044f\u043b[\u0430]?|\u043f\u0440\u0438\u043d\u044f\u0442\u043e|"
    r"ขอบคุณ(ค่ะ|ครับ)?|โอเค(ค่ะ|ครับ)?|ได้(ค่ะ|ครับ)?|"
    r"yes|yup|yeah|sure|alright|good|fine|\u0434\u0430|\u0430\u0433\u0430)"
    r"[\W_]*)+$",
    re.IGNORECASE,
)

# Pure greeting
GREET_PAT = re.compile(
    r"^[\W_]*"
    r"(hi|hii+|hey|hello+|good\s+(morning|afternoon|evening)|"
    r"สวัสดี(ค่ะ|ครับ)?|"
    r"\u043f\u0440\u0438\u0432\u0435\u0442(\u0438\u043a)?|\u0437\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435|\u0437\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439|\u0434\u043e\u0431\u0440(\u043e\u0435|\u044b\u0439)\s+(\u0443\u0442\u0440\u043e|\u0434\u0435\u043d\u044c|\u0432\u0435\u0447\u0435\u0440))"
    r"[\W_]*$",
    re.IGNORECASE,
)

EMOJI_ONLY = re.compile(
    r"^[\s\W_"
    r"\U0001F300-\U0001FAFF"
    r"\U0001F600-\U0001F64F"
    r"\U0001F680-\U0001F6FF"
    r"\U00002600-\U000027BF"
    r"\U0001F900-\U0001F9FF]*$"
)

NON_LETTER = re.compile(r"[\d\s\W_]")


def detect_lang(text: str) -> str:
    if not text:
        return "unknown"
    if THAI_RE.search(text):
        return "th"
    if CYR_RE.search(text):
        return "ru"
    for code, rx in LATIN_MARKERS.items():
        if rx.search(text):
            return code
    return "en"


def is_ack_or_greeting_or_emoji(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if EMOJI_ONLY.match(t):
        return True
    if GREET_PAT.match(t):
        return True
    if ACK_PAT.match(t):
        return True
    return False


def is_all_cyrillic(text: str) -> bool:
    """True iff every letter in text is Cyrillic (used by optional language filters)."""
    letters = NON_LETTER.sub("", text or "")
    if not letters:
        return False
    return bool(re.fullmatch(r"[\u0400-\u04ff]+", letters))
