"""Post-filter rules (sanitized port of the production rule set).

The production engine ended at 26-27 active rules after 21+ iterations; many
were domain-specific (bank-brand lists, named-person blocklists, topic
contradiction tables, geographic literals). This module ports the
domain-neutral core and parameterises the domain-specific bits through
``RuleContext`` (known_names, sensitive_topics, substantive_keywords).

Field conventions on the case dict: ``case``, ``solution``, ``status``,
``topic``, ``original_question`` / ``original_questions``, ``evidence_msg_ids``,
``msg_ids``, ``n_agent``, ``requester_text_len``, ``escalation_flag``,
``initiated_by``, ``volatile_kinds``.
"""
from __future__ import annotations

import re
from typing import Any

from ..extract.anonymize import has_raw_volatile
from .engine import RuleContext, RuleEngine

# ----------------------------------------------------------------------------- helpers

def _case(c: dict[str, Any]) -> str:
    return (c.get("canonical_case") or c.get("case") or "").strip()


def _sol(c: dict[str, Any]) -> str:
    return (c.get("canonical_solution") or c.get("solution") or "").strip()


def _oqs(c: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if c.get("original_question"):
        out.append(c["original_question"])
    for q in c.get("original_questions") or []:
        out.append(q if isinstance(q, str) else (q.get("text") or ""))
    for q in c.get("question_records") or []:
        if isinstance(q, dict):
            out.append(q.get("text") or "")
    return [o for o in out if o]


def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


# ----------------------------------------------------------------------------- rules

GREETING_STARTS = ("good morning", "good afternoon", "good evening", "hello", "hi ", "hey", "thank you", "thanks")
ACK_ONLY = {"thank you", "thanks", "ok", "okay", "yes", "noted", "received", "understood", "confirmed", "done", "sure"}


def reject_greeting_as_case(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    text = re.sub(r"[^\w\s]", "", _case(c).lower(), flags=re.UNICODE).strip()
    words = text.split()
    short = len(words) <= 4
    greet = any(text.startswith(g.strip()) for g in GREETING_STARTS)
    ack = text in ACK_ONLY or (words and all(w in ACK_ONLY for w in words))
    bad = short and (greet or ack)
    return (not bad, "case text is a short greeting/ack" if bad else "")


HOLDING_PATTERNS = [r"^please wait\b", r"^wait for\b", r"^i will check\b", r"^checking\b", r"^can you ask\b",
                    r"^could you ask\b", r"will get back to you", r"^how many\??$", r"^do you want",
                    r"^let me check\b", r"^on it\.?$"]


def reject_holding_ack_solution(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    s = _sol(c).lower()
    bad = any(re.search(p, s) for p in HOLDING_PATTERNS)
    return (not bad, "solution is a holding ack / counter-question, no real agent action" if bad else "")


def reject_topic_other_dump(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    bad = (c.get("topic") or "").strip().lower() == "other" and len(_case(c)) < 80
    return (not bad, "topic=other on a thin case" if bad else "")


COMPLIANCE_KW = ["the requester confirmed", "the requester sent", "the requester agreed", "requester confirmed",
                 "requester sent", "requester agreed", "the member confirmed", "the member sent", "member agreed",
                 "the employee confirmed", "the employee sent", "the employee agreed"]
WEAK_ACK = ["ok", "okay", "noted", "later", "thanks", "thank you", "received", "confirmed", "acknowledged"]


def reject_requester_compliance_solution(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    s = _sol(c).lower()
    has_compliance = any(k in s for k in COMPLIANCE_KW)
    weak_only = s in WEAK_ACK or (len(s) <= 25 and any(s == w or s.startswith(w + " ") or s.startswith(w + ",") for w in WEAK_ACK))
    bad = has_compliance or weak_only
    return (not bad, "solution describes requester compliance or is a one-word ack" if bad else "")


AGENT_ACTION_ACTIVE = re.compile(
    r"(?:\b(?:agent|staff|support|admin|reception)|<agent_name>)\s+(advised|confirmed|provided|transferred|escalated|scheduled|told|offered|"
    r"instructed|recommended|sent|gave|issued|arranged|approved|denied|identified|clarified|responded|explained|noted|verified|"
    r"checked|corrected|registered|booked|coordinated|reminded|asked|investigated|handled|processed|moved|blocked|assigned)\b", re.I)
AGENT_ACTION_PASSIVE = re.compile(
    r"\b(payment|amount|invoice|fee|booking|card|locker|pass|request|account|plan|application|document|registration|appointment|"
    r"schedule|policy|rule|exception)\s+(?:was|were|has\s+been|have\s+been|got)\s+(sent|made|issued|transferred|approved|verified|"
    r"confirmed|completed|processed|registered|booked|scheduled|cancelled|denied|rejected|assigned|forwarded|delivered|cleared|reset|"
    r"corrected|updated|validated|signed|blocked|moved|reissued)\b", re.I)


def reject_case_contains_agent_action(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    """Case body must describe the requester's situation; agent actions belong in solution (strict split)."""
    m = AGENT_ACTION_ACTIVE.search(_case(c)) or AGENT_ACTION_PASSIVE.search(_case(c))
    return (m is None, f'case body contains agent-action phrase "{m.group(0)[:40]}"' if m else "")


def reject_pii_leak(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    text = " ".join([_case(c), _sol(c)] + _oqs(c))
    found = has_raw_volatile(text, ctx.known_names)
    return (not found, f"raw volatile/PII detected: {found}" if found else "")


def reject_no_solution(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    s = _sol(c)
    has = bool(s) and s.lower() not in ("null", "none", "n/a")
    ok = has or (c.get("status") or "").lower() == "unresolved"
    return (ok, "" if ok else "solution empty AND status is not unresolved")


FABRICATED_DOC = [r"\b(agent|staff|support) sent (the )?required document\b", r"\b(agent|staff|support) provided (the )?required document\b",
                  r"\b(agent|staff|support) sent (the )?necessary document\b"]


def reject_fabricated_doc_solution(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    s = _sol(c).lower()
    bad = any(re.search(p, s) for p in FABRICATED_DOC)
    return (not bad, "templated 'agent sent required document' solution" if bad else "")


def reject_trivial_anchor_no_keyword(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    n_msgs = len(c.get("msg_ids") or []) or 1
    emp_len = c.get("requester_text_len") or 100
    txt = " ".join([_case(c), _sol(c)] + _oqs(c)).lower()
    kw = ctx.substantive_keywords
    has_kw = any(k in txt for k in kw) if kw else True
    thin = n_msgs <= 1 and emp_len < 50 and not has_kw
    return (not thin, "single message, requester_text_len<50, no substantive keyword" if thin else "")


REMINDER_RE = re.compile(r"\b(don'?t\s+forget|please\s+remember|reminder|as\s+i\s+said|like\s+before|thanks\s+again|thank\s+you\s+again)\b|\u043d\u0435 \u0437\u0430\u0431\u0443\u0434\u044c|อย่าลืม", re.I)


def reject_reminder_as_anchor(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    for oq in _oqs(c):
        o = oq.strip()
        if (len(o) <= 30 or len(o.split()) <= 8) and REMINDER_RE.search(o) and "?" not in o:
            return (False, f"original_question is a short reminder/imperative ({o[:40]})")
    return (True, "")


MID_THREAD_RE = re.compile(r"\byes\s+i\s+understand[\s.,]*but\b|^(yes|ok|\u0434\u0430|\u043f\u043e\u043d\u044f\u043b|เข้าใจ)[^.!?]{0,25}?(\bbut\b|\b\u043d\u043e\b|แต่)|\bok\s+but\b", re.I)


def reject_mid_thread_reaction(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    for oq in _oqs(c):
        if MID_THREAD_RE.search(oq.strip()):
            return (False, "original_question is a mid-thread reaction pattern")
    return (True, "")


REACTIVE_RE = re.compile(r"\b(it means|does it mean|do you mean|so we|so that means|together\?)\b", re.I)


def reject_agent_triggered_reactive_clarification(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    if (c.get("initiated_by") or "").lower() != "agent_action_triggered":
        return (True, "")
    oq = " ".join(_oqs(c))
    if len(oq.split()) < 20 and REACTIVE_RE.search(oq):
        return (False, "agent-triggered case with a short reactive clarification as the question")
    return (True, "")


def reject_evidence_ids_incomplete(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    n_agent = c.get("n_agent") or 0
    ev = c.get("evidence_msg_ids") or []
    msg_ids = c.get("msg_ids") or []
    if n_agent >= 2 and not ev and len(msg_ids) >= 4:
        return (False, f"n_agent={n_agent} but evidence_msg_ids is empty")
    if n_agent >= 4 and len(ev) <= 1:
        return (False, f"n_agent={n_agent} but only {len(ev)} evidence ids (suspicious gap)")
    return (True, "")


def reject_oq_not_in_evidence(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    """Grounding: original_question must share a contiguous token run with a requester message in the slice.

    Placeholders are stripped before matching. min_run = 3 (short) / 4 (>=7 tokens) / len-1 (<=3 tokens).
    Safety net: if the slice is unavailable, the rule passes.
    """
    if not ctx.messages:
        return (True, "")
    oqs = _oqs(c)
    if not oqs:
        return (True, "")
    ids = [int(i) for i in (c.get("evidence_msg_ids") or [])] or [int(i) for i in (c.get("msg_ids") or [])]
    texts = [ctx.messages[i].text for i in ids if i in ctx.messages and ctx.messages[i].from_role == "requester"]
    if not texts:
        return (True, "")
    norm_texts = [_norm(t) for t in texts]
    min_run = 3
    for oq in oqs:
        toks = _norm(oq).split()
        if not toks:
            continue
        min_run = 3 if len(toks) < 7 else 4
        if len(toks) <= 3:
            min_run = max(2, len(toks) - 1)
        for i in range(len(toks) - min_run + 1):
            window = " ".join(toks[i:i + min_run])
            if any(window in t for t in norm_texts):
                return (True, "")
    return (False, f"original_question not grounded in any requester message (>= {min_run} consecutive tokens required)")


def reject_missing_escalation_flag(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    ok = isinstance(c.get("escalation_flag"), bool)
    return (ok, "" if ok else "escalation_flag missing or not bool")


def reject_wrong_escalation_flag_for_sensitive_topic(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    topic = (c.get("topic") or "").lower()
    if topic in ctx.sensitive_topics and c.get("escalation_flag") is False:
        return (False, f"topic={topic} is agent-authoritative and requires escalation_flag=true")
    return (True, "")


DOMAIN_SIGNALS = {
    "connectivity": r"\b(wifi|internet|network|vpn|ethernet)\b",
    "billing": r"\b(invoice|fee|charged|refund|billing|payment)\b",
    "access": r"\b(access card|door|reader|badge|key)\b",
    "booking": r"\b(meeting room|booking|booked|calendar)\b",
    "facilities": r"\b(printer|coffee|air con|ac|temperature|locker|parking)\b",
    "membership": r"\b(plan|membership|dedicated desk|hot desk|upgrade)\b",
}


def reject_composite_multi_topic(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    full = (_case(c) + " " + _sol(c)).lower()
    if len(full.split()) < 150:
        return (True, "")
    hit = [k for k, rx in DOMAIN_SIGNALS.items() if re.search(rx, full)]
    if len(hit) >= 3:
        return (False, f"case spans {len(hit)} domains ({', '.join(hit)}) in a long record; split it")
    return (True, "")


def reject_date_leak_when_declared(c: dict[str, Any], ctx: RuleContext) -> tuple[bool, str]:
    if "date" not in (c.get("volatile_kinds") or []):
        return (True, "")
    combined = re.sub(r"<[^>]+>", " ", " ".join([_case(c), _sol(c)] + _oqs(c)))
    m = re.search(r"\b\d{1,2}[./-]\d{2}(?:[./-]\d{2,4})?\b", combined)
    return (m is None, f"raw date '{m.group(0)}' despite volatile_kinds=[date]" if m else "")


def default_engine() -> RuleEngine:
    """Registration order = evaluation order (cheap regex first, grounding last)."""
    e = RuleEngine()
    e.add("reject_greeting_as_case", reject_greeting_as_case, "short greeting/ack emitted as a case")
    e.add("reject_holding_ack_solution", reject_holding_ack_solution, "'I will check' stored as the solution")
    e.add("reject_topic_other_dump", reject_topic_other_dump, "topic=other used as a dump bucket")
    e.add("reject_requester_compliance_solution", reject_requester_compliance_solution, "'the requester sent X' is not a solution")
    e.add("reject_case_contains_agent_action", reject_case_contains_agent_action, "case/solution strict split (active + passive voice)")
    e.add("reject_pii_leak", reject_pii_leak, "phones / cards / amounts / emails / names leaked into the KB")
    e.add("reject_no_solution", reject_no_solution, "null solution without status=unresolved")
    e.add("reject_fabricated_doc_solution", reject_fabricated_doc_solution, "templated solution never said by the agent")
    e.add("reject_trivial_anchor_no_keyword", reject_trivial_anchor_no_keyword, "one-liner thread with no substantive content")
    e.add("reject_reminder_as_anchor", reject_reminder_as_anchor, "'don't forget X' taken as a question")
    e.add("reject_mid_thread_reaction", reject_mid_thread_reaction, "'yes but...' reaction taken as a question")
    e.add("reject_agent_triggered_reactive_clarification", reject_agent_triggered_reactive_clarification, "reaction to an agent broadcast")
    e.add("reject_evidence_ids_incomplete", reject_evidence_ids_incomplete, "worker did not propagate agent turns as evidence")
    e.add("reject_missing_escalation_flag", reject_missing_escalation_flag, "every case must say whether a human must act")
    e.add("reject_wrong_escalation_flag_for_sensitive_topic", reject_wrong_escalation_flag_for_sensitive_topic, "money/account/state-change topics are agent-authoritative")
    e.add("reject_composite_multi_topic", reject_composite_multi_topic, "one record spanning 3+ domains")
    e.add("reject_date_leak_when_declared", reject_date_leak_when_declared, "volatile_kinds is a declaration, not the act of scrubbing")
    e.add("reject_oq_not_in_evidence", reject_oq_not_in_evidence, "fabricated original_question (token-run grounding)")
    return e
