"""Ingest: load exported chat messages and assign roles.

Input format (JSONL, one message per line)::

    {"chat_id": "...", "msg_id": 1, "ts": 1700000000, "from_id": "u1",
     "text": "...", "reply_to": null, "from_role": "requester"|"agent" (optional)}

If ``from_role`` is absent, roles are inferred heuristically: a sender active
in >= ``min_chats_for_agent`` distinct chats is an agent (support staff answer
in many chats; requesters usually write in one).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ..io import read_jsonl
from ..models import Message
from ..normalize.lang import detect_lang

SYSTEM_FROM_IDS = {"system"}
MIN_CHATS_FOR_AGENT = 2


def load_messages(path: str | Path, infer_roles: bool = True) -> list[Message]:
    rows = list(read_jsonl(path))
    msgs = [Message.from_dict(d) for d in rows]
    msgs = [m for m in msgs if m.text]
    for m in msgs:
        m.lang = detect_lang(m.text)
    has_roles = all(("from_role" in d or "role" in d) for d in rows)
    if infer_roles and not has_roles:
        roles = assign_roles(msgs)
        for m in msgs:
            m.from_role = roles[m.from_id]
    return msgs


def assign_roles(messages: list[Message], min_chats_for_agent: int = MIN_CHATS_FOR_AGENT) -> dict[str, str]:
    chats: dict[str, set[str]] = defaultdict(set)
    for m in messages:
        chats[m.from_id].add(m.chat_id)
    roles: dict[str, str] = {}
    for fid, cs in chats.items():
        if fid in SYSTEM_FROM_IDS:
            roles[fid] = "system"
        elif len(cs) >= min_chats_for_agent:
            roles[fid] = "agent"
        else:
            roles[fid] = "requester"
    return roles
