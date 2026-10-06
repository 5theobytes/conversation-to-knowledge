"""Utterance index: the original-language phrasings behind each canonical case.

Deterministic: source = question_records (text, lang, ts, thread_id);
dedupe on normalised text keeping the earliest ts; sort by ts; never
translate. Every case_id is present even when it has no utterances (flagged).
"""
from __future__ import annotations

import re

from ..models import CanonicalCase
from ..normalize.lang import detect_lang


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def build_utterance_index(cases: list[CanonicalCase]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cases:
        seen: dict[str, dict] = {}
        for q in sorted(c.question_records, key=lambda r: (r.get("ts") or 0)):
            k = _norm(q.get("text", ""))
            if not k:
                continue
            if k in seen:
                seen[k].setdefault("also_seen_in", []).append(q.get("thread_id"))
                continue
            seen[k] = {"text": q["text"], "lang": q.get("lang") or detect_lang(q["text"]),
                       "ts": q.get("ts"), "thread_id": q.get("thread_id")}
        utts = list(seen.values())
        out[c.case_id] = {"case_id": c.case_id, "topic": c.topic, "utterances": utts,
                          "flag_no_utterances": not utts}
    return out
