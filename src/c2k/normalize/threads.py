"""Requester-driven thread reconstruction.

Rules (per chat, messages sorted by (ts, msg_id)):

* a thread OPENS on any requester message (even "hello");
* consecutive requester messages glue into the same thread;
* agent replies extend the thread;
* a thread CLOSES when
    - the last requester message was a pure ack/greeting/emoji AND
      ``ack_gap_s`` of silence passed, OR
    - ``hard_gap_s`` passed since the last message in the thread;
* agent messages with no open thread are ignored (an agent cannot open a case:
  broadcasts and proactive announcements are not requests for help).

The thread is flagged ``has_substantive_requester_msg`` if at least one
requester message is not pure chatter. Only those are sent downstream.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from ..models import Message, Thread
from .lang import detect_lang, is_ack_or_greeting_or_emoji

HARD_GAP_S = 12 * 3600
ACK_GAP_S = 30 * 60


def build_threads(
    messages: list[Message],
    hard_gap_s: int = HARD_GAP_S,
    ack_gap_s: int = ACK_GAP_S,
) -> list[Thread]:
    by_chat: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        if m.from_role == "system":
            continue
        if m.lang == "unknown":
            m.lang = detect_lang(m.text)
        by_chat[m.chat_id].append(m)

    threads: list[Thread] = []
    for chat_id, msgs in by_chat.items():
        msgs.sort(key=lambda x: (x.ts, x.msg_id))
        current: list[Message] = []
        ack_pending = False

        def flush() -> None:
            nonlocal current, ack_pending
            if current:
                threads.append(_finalize(current))
            current = []
            ack_pending = False

        for m in msgs:
            if current and (m.ts - current[-1].ts) > hard_gap_s:
                flush()
            if current and ack_pending and (m.ts - current[-1].ts) > ack_gap_s:
                flush()

            if m.from_role == "requester":
                current.append(m)
                ack_pending = is_ack_or_greeting_or_emoji(m.text)
            elif m.from_role == "agent":
                if not current:
                    continue  # agent cannot open a thread
                current.append(m)
                ack_pending = False
        flush()
    return threads


def _finalize(group: list[Message]) -> Thread:
    roles = Counter(m.from_role for m in group)
    req = [m for m in group if m.from_role == "requester"]
    langs = Counter(m.lang for m in req)
    lang_majority = langs.most_common(1)[0][0] if langs else "unknown"
    has_substantive = any(not is_ack_or_greeting_or_emoji(m.text) for m in req)
    agent_present = roles.get("agent", 0) > 0
    last_req = next((m for m in reversed(group) if m.from_role == "requester"), None)
    last_was_ack = bool(last_req and is_ack_or_greeting_or_emoji(last_req.text))
    return Thread(
        thread_id=f"{group[0].chat_id}:{group[0].msg_id}",
        chat_id=group[0].chat_id,
        msg_ids=[m.msg_id for m in group],
        ts_first=group[0].ts,
        ts_last=group[-1].ts,
        n_requester=roles.get("requester", 0),
        n_agent=roles.get("agent", 0),
        lang_majority=lang_majority,
        requester_text_len=sum(len(m.text) for m in req),
        has_substantive_requester_msg=has_substantive,
        has_resolution_signal=agent_present and last_was_ack,
    )
