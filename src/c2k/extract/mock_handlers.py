"""Default MockLLM handlers, one per LLM-backed task.

They implement the *contract* of each role prompt in ``agents/`` with cheap
keyword heuristics so the pipeline runs offline. They are not models and make
no claim of accuracy beyond the synthetic corpus.
"""
from __future__ import annotations

from typing import Any

from . import lexicon as lx
from .anonymize import scrub
from ..normalize.lang import detect_lang, is_ack_or_greeting_or_emoji


def _requester_msgs(p: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in p["messages"] if m["from_role"] == "requester"]


def _agent_msgs(p: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in p["messages"] if m["from_role"] == "agent"]


def _anchor(p: dict[str, Any]) -> dict[str, Any] | None:
    for m in _requester_msgs(p):
        if not is_ack_or_greeting_or_emoji(m["text"]):
            return m
    return None


# --- task: needs_help --------------------------------------------------------
def needs_help(p: dict[str, Any]) -> dict[str, Any]:
    msgs = p["messages"]
    anchor = _anchor(p)
    base = {"thread_id": p["thread_id"], "needs_help": False, "confidence": "high",
            "question_paraphrase": None, "first_help_msg_id": None, "topic_hint": None,
            "sensitive_topic_signal": False}
    if anchor is None:
        return {**base, "reason": "GREETING_AND_ACK_TRASH"}
    if msgs and msgs[0]["from_role"] == "agent":
        return {**base, "reason": "AGENT_INITIATED_NO_REQUESTER_ASK"}
    txt = anchor["text"]
    if lx.COMPLIANCE_RE.search(txt):
        return {**base, "reason": "REQUESTER_COMPLIANCE_ONLY"}
    if lx.REMINDER_RE.search(txt) and "?" not in txt and len(txt.split()) <= 8:
        return {**base, "reason": "REMINDER_AS_ANCHOR"}
    if lx.MID_THREAD_RE.search(txt):
        return {**base, "reason": "MID_THREAD_REPLY"}
    if len(txt) < 30 and "?" not in txt:
        return {**base, "reason": "TOO_THIN", "confidence": "low"}
    topic = lx.guess_topic(txt)
    return {**base, "needs_help": True, "first_help_msg_id": anchor["msg_id"], "topic_hint": topic,
            "question_paraphrase": f"Requester asks for help with {topic.replace('_', ' ')}.",
            "reason": "substantive requester ask present",
            "sensitive_topic_signal": topic in lx.SENSITIVE_TOPICS}


# --- task: extract -----------------------------------------------------------
def extract(p: dict[str, Any]) -> dict[str, Any]:
    anchor = _anchor(p)
    if anchor is None:
        return {"cases": [], "drop_reason": "NO_REQUESTER_QUESTION"}
    names = p.get("known_names", [])
    req_text = " ".join(m["text"] for m in _requester_msgs(p))
    topic = p.get("topic_hint") or lx.guess_topic(req_text)
    if topic == "other":
        topic = lx.guess_topic(req_text)
    intent, template = lx.guess_intent(topic, req_text)

    agent = [m for m in _agent_msgs(p) if not is_ack_or_greeting_or_emoji(m["text"])]
    substantive = [m for m in agent if not lx.HOLDING_ACK_RE.search(m["text"].strip())]
    evidence = [anchor["msg_id"]] + [m["msg_id"] for m in agent]
    kinds: set[str] = set()
    if substantive:
        last = substantive[-1]
        s = scrub(last["text"], names)
        kinds.update(s.kinds)
        if lx.ESCALATION_RE.search(last["text"]):
            status = "escalated"
        elif any(k in last["text"].lower() for k in ("moved", "cleared", "blocked", "assigned", "\u043f\u0435\u0440\u0435\u043d\u0451\u0441", "\u043f\u043e\u0447\u0438\u043d\u0438\u043b\u0438", "\u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d\u0430", "\u0437\u0430\u043a\u0440\u0435\u043f\u0438\u043b", "ย้าย", "แก้ให้", "ระงับบัตรเก่า", "จัดล็อกเกอร์", "found it", "\u043d\u0430\u0448\u0451\u043b", "เจอแล้ว", "sent the", "\u043e\u0442\u043f\u0440\u0430\u0432\u0438\u043b \u0444\u043e\u0440\u043c\u0443", "ส่งแบบฟอร์ม", "it's in the mailroom", "\u043b\u0435\u0436\u0438\u0442", "มีค่ะ")):
            status = "resolved"
        else:
            status = "informational"
        solution = f"Agent response: {s.text}"
    else:
        status = "unresolved"
        solution = "Agent acknowledged the request; no concrete resolution within the thread slice."
    oq = scrub(anchor["text"], names)
    kinds.update(oq.kinds)
    case = template
    return {"cases": [{
        "topic": topic, "intent": intent, "case": case, "solution": solution, "status": status,
        "original_question": oq.text, "original_question_lang": detect_lang(anchor["text"]),
        "evidence_msg_ids": evidence, "volatile_kinds": sorted(kinds),
        "escalation_flag": (topic in lx.SENSITIVE_TOPICS) or bool(p.get("sensitive_topic_signal")) or status == "escalated",
        "initiated_by": "requester",
    }]}


# --- task: merge -------------------------------------------------------------
def merge(p: dict[str, Any]) -> dict[str, Any]:
    inputs = p["inputs"]
    case = max((i["case"] for i in inputs), key=len)
    # The mock cannot translate, so it keeps one language per solution: English members win
    # when present (a real merge model rewrites all variants in the KB language).
    by_lang: dict[str, list[str]] = {}
    for i in inputs:
        s = (i.get("solution") or "").strip()
        if s:
            by_lang.setdefault(detect_lang(s), []).append(s)
    chosen = by_lang.get("en") or next(iter(by_lang.values()), [])
    sols: list[str] = []
    for s in chosen:
        if s not in sols:
            sols.append(s)
    if len(sols) <= 1:
        solution = sols[0] if sols else None
    else:
        solution = " ".join(f"Variant {n}: {s}" for n, s in enumerate(sols, 1))
    kinds = sorted({k for i in inputs for k in (i.get("volatile_kinds") or [])})
    return {"case": case, "solution": solution, "volatile_kinds": kinds}


# --- task: leads_to ----------------------------------------------------------
def leads_to(p: dict[str, Any]) -> dict[str, Any]:
    a, b = p["case_a"], p["case_b"]
    hint = lx.LEADS_TO_HINTS.get((a.get("topic"), a.get("intent")))
    return {"answer": "YES" if hint and hint == b.get("intent") else "NO"}


# --- task: answer ------------------------------------------------------------
def answer(p: dict[str, Any]) -> dict[str, Any]:
    lang = p.get("lang", "en")
    hits = p.get("hits", [])
    if not hits or hits[0]["cosine"] < p.get("threshold", 0.55):
        txt = {"en": "I don't have a confirmed past resolution for this; passing it to a human agent.",
               "ru": "I do not have a confirmed resolution for this; passing it to a human agent.",
               "th": "ยังไม่มีแนวทางแก้ไขที่ยืนยันแล้วสำหรับเรื่องนี้ ขอส่งต่อให้เจ้าหน้าที่ค่ะ"}[lang]
        return {"answer": txt, "based_on": [], "escalate": True}
    top = hits[0]
    sol = top.get("solution") or ""
    esc = bool(top.get("escalation_flag"))
    if not sol or top.get("status") == "unresolved":
        txt = {"en": "This situation is known but has no confirmed resolution yet; I'm escalating it to a human agent.",
               "ru": "This situation is known, but no confirmed resolution is available; passing it to a human agent.",
               "th": "เรื่องนี้เคยเกิดขึ้นแต่ยังไม่มีแนวทางที่ยืนยัน ขอส่งต่อให้เจ้าหน้าที่ค่ะ"}[lang]
        return {"answer": txt, "based_on": [top["case_id"]], "escalate": True}
    lead = {"en": "Based on a similar past case: ", "ru": "Based on a similar past case: ", "th": "จากกรณีที่คล้ายกันก่อนหน้านี้: "}[lang]
    tail = ""
    if esc:
        tail = {"en": " This needs confirmation or action by a staff member, so I'm also flagging it to them.",
                "ru": " This requires staff confirmation or action, so I am also passing it to a human agent.",
                "th": " เรื่องนี้ต้องให้เจ้าหน้าที่ยืนยันหรือดำเนินการ จึงแจ้งเจ้าหน้าที่ให้ด้วยค่ะ"}[lang]
    sol_plain = sol.replace("Agent response: ", "")
    thr = p.get("threshold", 0.55)
    return {"answer": lead + sol_plain + tail,
            "based_on": [h["case_id"] for h in hits[:2] if h["cosine"] >= thr], "escalate": esc}


def register_all(mock: Any) -> None:
    mock.register("needs_help", needs_help)
    mock.register("extract", extract)
    mock.register("merge", merge)
    mock.register("leads_to", leads_to)
    mock.register("answer", answer)
