"""LLM-backed stages: needs_help (pre-qualifier) and extract.

Both take a thread + its messages, build the role prompt + JSON payload and
call the provider. Every negative decision is logged as a ``DropRecord``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import DropRecord, Message, NeedsHelpVerdict, RawCase, Thread
from .llm import LLMProvider
from .prompts import load_prompt


def _thread_payload(thread: Thread, messages: dict[int, Message]) -> dict[str, Any]:
    return {
        "thread_id": thread.thread_id,
        "chat_id": thread.chat_id,
        "n_requester": thread.n_requester,
        "n_agent": thread.n_agent,
        "requester_text_len": thread.requester_text_len,
        "messages": [
            {"msg_id": mid, "ts": messages[mid].ts, "from_role": messages[mid].from_role,
             "from_id": messages[mid].from_id, "text": messages[mid].text, "reply_to": messages[mid].reply_to}
            for mid in thread.msg_ids if mid in messages
        ],
    }


def run_needs_help(threads: list[Thread], messages: dict[int, Message], llm: LLMProvider,
                   drops: list[DropRecord]) -> list[NeedsHelpVerdict]:
    system = load_prompt("worker_needs_help")
    out: list[NeedsHelpVerdict] = []
    for t in threads:
        if not t.has_substantive_requester_msg:
            drops.append(DropRecord("normalize", t.thread_id, "NO_SUBSTANTIVE_REQUESTER_MSG"))
            continue
        r = llm.complete_json(system, json.dumps(_thread_payload(t, messages), ensure_ascii=False))
        v = NeedsHelpVerdict(
            thread_id=t.thread_id, needs_help=bool(r.get("needs_help")),
            confidence=r.get("confidence", "medium"), question_paraphrase=r.get("question_paraphrase"),
            first_help_msg_id=r.get("first_help_msg_id"), topic_hint=r.get("topic_hint"),
            reason=r.get("reason", ""), sensitive_topic_signal=bool(r.get("sensitive_topic_signal")),
        )
        if v.needs_help and v.first_help_msg_id is not None and v.first_help_msg_id not in t.msg_ids:
            # the contract: anchor must exist in the slice; otherwise treat as a mock/model error
            v.needs_help = False
            v.reason = "INVALID_ANCHOR_MSG_ID"
        if not v.needs_help:
            drops.append(DropRecord("worker_needs_help", t.thread_id, v.reason))
        out.append(v)
    return out


def run_extract(threads: list[Thread], verdicts: list[NeedsHelpVerdict], messages: dict[int, Message],
                llm: LLMProvider, drops: list[DropRecord], known_names: list[str] | None = None) -> list[RawCase]:
    system = load_prompt("worker_extract")
    by_id = {t.thread_id: t for t in threads}
    out: list[RawCase] = []
    for v in verdicts:
        if not v.needs_help:
            continue
        t = by_id[v.thread_id]
        payload = _thread_payload(t, messages)
        payload.update({"topic_hint": v.topic_hint, "question_paraphrase": v.question_paraphrase,
                        "sensitive_topic_signal": v.sensitive_topic_signal, "known_names": known_names or []})
        r = llm.complete_json(system, json.dumps(payload, ensure_ascii=False))
        cases = r.get("cases") or []
        if not cases:
            drops.append(DropRecord("worker_extract", t.thread_id, r.get("drop_reason", "NO_CASE"),
                                    "prequalifier_disagreement=true"))
            continue
        req_from = next((messages[m].from_id for m in t.msg_ids if messages[m].from_role == "requester"), "")
        for i, c in enumerate(cases):
            ev = [int(x) for x in (c.get("evidence_msg_ids") or []) if int(x) in t.msg_ids]
            if not c.get("topic"):
                drops.append(DropRecord("worker_extract", t.thread_id, "TOPIC_MISSING"))
                continue
            raw_id = "r-" + hashlib.sha1(f"{t.thread_id}|{i}|{c.get('case')}".encode("utf-8")).hexdigest()[:10]
            out.append(RawCase(
                raw_id=raw_id, thread_id=t.thread_id, chat_id=t.chat_id, from_id=req_from,
                topic=c["topic"], case=c.get("case") or "", solution=c.get("solution"),
                status=c.get("status") or "unresolved", original_question=c.get("original_question") or "",
                original_question_lang=c.get("original_question_lang") or "unknown",
                evidence_msg_ids=ev, msg_ids=list(t.msg_ids), ts_first=t.ts_first, ts_last=t.ts_last,
                n_agent=t.n_agent, n_requester=t.n_requester, requester_text_len=t.requester_text_len,
                escalation_flag=bool(c.get("escalation_flag", False)) or v.sensitive_topic_signal,
                initiated_by=c.get("initiated_by") or "requester",
                volatile_kinds=list(c.get("volatile_kinds") or []),
            ))
            # carry the mock's sub-intent for the LEADS_TO judge (a real model would infer it)
            setattr(out[-1], "_intent", c.get("intent"))
    return out
