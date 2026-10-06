from conftest import msg

from c2k.validate.engine import RuleContext, RuleEngine
from c2k.validate.rules import default_engine

E = default_engine()
R = {r.name: r.fn for r in E.rules}
CTX = RuleContext(sensitive_topics={"invoice_billing"}, known_names=["Mira Okonkwo"], substantive_keywords=["printer"])


def base(**kw):
    d = {"case": "A member reports the printer near the kitchen shows a paper jam.", "solution": "Agent response: cleared the rear tray sensor.",
         "status": "resolved", "topic": "printer_issue", "original_question": "printer jammed again", "evidence_msg_ids": [1, 2],
         "msg_ids": [1, 2, 3], "n_agent": 1, "requester_text_len": 80, "escalation_flag": False, "initiated_by": "requester",
         "volatile_kinds": []}
    d.update(kw)
    return d


def test_clean_case_passes_all_rules():
    v = E.evaluate(base(), CTX, explain=True)
    assert v.keep, v.reason
    assert len(v.trace) == len(E.names())


def test_greeting_as_case():
    assert not R["reject_greeting_as_case"](base(case="Good morning!"), CTX)[0]
    assert R["reject_greeting_as_case"](base(), CTX)[0]


def test_holding_ack_solution():
    assert not R["reject_holding_ack_solution"](base(solution="I will check and get back"), CTX)[0]
    assert R["reject_holding_ack_solution"](base(), CTX)[0]


def test_requester_compliance_or_weak_ack_solution():
    assert not R["reject_requester_compliance_solution"](base(solution="The requester sent the photo"), CTX)[0]
    assert not R["reject_requester_compliance_solution"](base(solution="ok"), CTX)[0]
    assert R["reject_requester_compliance_solution"](base(), CTX)[0]


def test_case_contains_agent_action_active_and_passive():
    assert not R["reject_case_contains_agent_action"](base(case="Agent confirmed the amount and moved the booking."), CTX)[0]
    assert not R["reject_case_contains_agent_action"](base(case="The invoice was reissued after the member complained."), CTX)[0]
    assert R["reject_case_contains_agent_action"](base(), CTX)[0]


def test_pii_leak_rule_uses_context_names():
    assert not R["reject_pii_leak"](base(solution="call Mira at +1 555 010 2233"), CTX)[0]
    assert not R["reject_pii_leak"](base(original_question="invoice shows 120 USD"), CTX)[0]
    assert R["reject_pii_leak"](base(original_question="invoice shows <amount>"), CTX)[0]


def test_no_solution_requires_unresolved_status():
    assert not R["reject_no_solution"](base(solution=None, status="resolved"), CTX)[0]
    assert R["reject_no_solution"](base(solution=None, status="unresolved"), CTX)[0]


def test_reminder_and_mid_thread_anchors():
    assert not R["reject_reminder_as_anchor"](base(original_question="don't forget my locker key tomorrow"), CTX)[0]
    assert R["reject_reminder_as_anchor"](base(original_question="did you forget my locker key? it is still missing"), CTX)[0]
    assert not R["reject_mid_thread_reaction"](base(original_question="yes I understand, but it still doesn't work"), CTX)[0]
    assert not R["reject_mid_thread_reaction"](base(original_question="yes I understand, but it still does not work"), CTX)[0]


def test_evidence_ids_incomplete():
    assert not R["reject_evidence_ids_incomplete"](base(n_agent=3, evidence_msg_ids=[], msg_ids=[1, 2, 3, 4]), CTX)[0]
    assert not R["reject_evidence_ids_incomplete"](base(n_agent=5, evidence_msg_ids=[1]), CTX)[0]
    assert R["reject_evidence_ids_incomplete"](base(n_agent=2, evidence_msg_ids=[1, 2]), CTX)[0]


def test_escalation_flag_rules():
    d = base(); del d["escalation_flag"]
    assert not R["reject_missing_escalation_flag"](d, CTX)[0]
    assert not R["reject_wrong_escalation_flag_for_sensitive_topic"](base(topic="invoice_billing", escalation_flag=False), CTX)[0]
    assert R["reject_wrong_escalation_flag_for_sensitive_topic"](base(topic="invoice_billing", escalation_flag=True), CTX)[0]


def test_trivial_anchor_without_keyword():
    thin = base(case="hm", solution="x", original_question="hm", msg_ids=[1], requester_text_len=5)
    assert not R["reject_trivial_anchor_no_keyword"](thin, CTX)[0]
    assert R["reject_trivial_anchor_no_keyword"](base(msg_ids=[1], requester_text_len=5), CTX)[0]   # 'printer' keyword present


def test_oq_grounding_against_message_slice():
    ctx = RuleContext(messages={
        1: msg("c", 1, 0, "u1", "Hello, the printer near the kitchen is jammed again since this morning"),
        2: msg("c", 2, 10, "a1", "Cleared it."),
    })
    ok, _ = R["reject_oq_not_in_evidence"](base(original_question="the printer near the kitchen is jammed", evidence_msg_ids=[1, 2]), ctx)
    assert ok
    ok, reason = R["reject_oq_not_in_evidence"](base(original_question="Did you make the payment for my phone?", evidence_msg_ids=[1, 2]), ctx)
    assert not ok and "not grounded" in reason
    # placeholders are stripped before matching
    ok, _ = R["reject_oq_not_in_evidence"](base(original_question="the printer near the <location> is jammed", evidence_msg_ids=[1, 2]), ctx)
    assert ok


def test_date_leak_when_declared():
    assert not R["reject_date_leak_when_declared"](base(volatile_kinds=["date"], solution="come on 12.03"), CTX)[0]
    assert R["reject_date_leak_when_declared"](base(volatile_kinds=["date"], solution="come on <date>"), CTX)[0]


def test_engine_short_circuits_and_explains():
    e = RuleEngine()
    e.add("a", lambda c, x: (True, ""))
    e.add("b", lambda c, x: (False, "boom"))
    e.add("c", lambda c, x: (False, "later"))
    v = e.evaluate({}, explain=False)
    assert not v.keep and v.failed_rule == "b" and len(v.trace) == 2
    v = e.evaluate({}, explain=True)
    assert len(v.trace) == 3
    e.disable("b")
    assert e.evaluate({}).failed_rule == "c"
    assert "b" not in e.names()
