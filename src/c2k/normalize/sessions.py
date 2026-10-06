"""Session cutter (the simplified "sequential" pipeline variant).

1. 12h gap: within a chat, split whenever consecutive messages differ by > gap.
2. Dyad rule: a session may contain at most 2 distinct senders. When a 3rd
   sender appears:
     * if any already-known sender has a LATER message in this session the
       whole session is dropped as ``multi_overlap`` (interleaved group talk);
     * otherwise the session is SPLIT right before that message.
   Applied recursively.
"""
from __future__ import annotations

from collections import defaultdict

from ..models import DropRecord, Message, Session

GAP_S = 12 * 3600


def cut_sessions(messages: list[Message], gap_s: int = GAP_S) -> tuple[list[Session], list[DropRecord]]:
    by_chat: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        if m.from_role != "system":
            by_chat[m.chat_id].append(m)

    sessions: list[Session] = []
    drops: list[DropRecord] = []
    for chat_id, msgs in by_chat.items():
        msgs.sort(key=lambda x: (x.ts, x.msg_id))
        chunk: list[Message] = []
        for m in msgs:
            if chunk and (m.ts - chunk[-1].ts) > gap_s:
                _emit(chunk, sessions, drops)
                chunk = []
            chunk.append(m)
        if chunk:
            _emit(chunk, sessions, drops)
    return sessions, drops


def _emit(chunk: list[Message], out: list[Session], drops: list[DropRecord],
          parent: str | None = None, idx: int = 0) -> None:
    sid = f"{chunk[0].chat_id}:{chunk[0].msg_id}"
    known: list[str] = []
    for i, m in enumerate(chunk):
        if m.from_id in known:
            continue
        if len(known) < 2:
            known.append(m.from_id)
            continue
        # a third sender appears at position i
        later_known = any(x.from_id in known for x in chunk[i + 1:])
        if later_known:
            drops.append(DropRecord("cut_sessions", sid, "multi_overlap", f"3rd sender {m.from_id} interleaved"))
            return
        head, tail = chunk[:i], chunk[i:]
        root = parent or sid
        out.append(_make(head, root, idx, True))
        _emit(tail, out, drops, parent=root, idx=idx + 1)
        return
    out.append(_make(chunk, parent, idx, parent is not None))


def _make(chunk: list[Message], parent: str | None, idx: int, is_split: bool) -> Session:
    return Session(
        session_id=f"{chunk[0].chat_id}:{chunk[0].msg_id}",
        chat_id=chunk[0].chat_id,
        msg_ids=[m.msg_id for m in chunk],
        ts_first=chunk[0].ts,
        ts_last=chunk[-1].ts,
        participant_ids=sorted({m.from_id for m in chunk}),
        role_first=chunk[0].from_role,
        parent_session_id=parent if is_split else None,
        split_idx=idx if is_split else 0,
    )
