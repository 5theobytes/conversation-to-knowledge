import json

from c2k.extract.llm import MockLLM, extract_json, parse_task
from c2k.pipeline import PipelineConfig, run_pipeline
from c2k.retrieve.answer import answer_question
from c2k.validate.kb_checks import validate_kb

NAMES = ["Mira Okonkwo", "Dariusz Lind", "Ananya Pillai", "Tomas Vega", "Zhanna Kirilenko", "Rustam Aliyev",
         "Vera Tsoi", "Niran Chaiya", "Pimchan Suwan", "Kiet Boonmee"]


def test_parse_task_and_extract_json():
    assert parse_task("<!-- task: extract -->\n# prompt") == "extract"
    assert parse_task("no tag") == "unknown"
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('text before {"a": [1, 2]} after') == {"a": [1, 2]}


def test_mock_llm_dispatches_by_task():
    m = MockLLM()
    r = m.complete_json("<!-- task: leads_to -->", json.dumps({"case_a": {"topic": "x", "intent": "a"}, "case_b": {"intent": "b"}}))
    assert r == {"answer": "NO"}
    assert m.calls[0][0] == "leads_to"


def test_synthetic_corpus_is_reproducible():
    from make_synthetic import generate
    assert generate(seed=7, n_conversations=10) == generate(seed=7, n_conversations=10)
    assert generate(seed=7, n_conversations=10) != generate(seed=8, n_conversations=10)


def test_pipeline_end_to_end_offline(synthetic_messages):
    cfg = PipelineConfig(known_names=NAMES, related_min=0.5, leads_lo=0.3)
    res = run_pipeline(synthetic_messages, config=cfg)
    st = res.stats()
    assert st["threads"] >= 35
    assert st["raw_cases"] >= 25
    assert 10 <= st["canonical_cases"] <= 30
    assert st["topics"] >= 10
    # noise threads are dropped with named reasons
    reasons = st["drops_by_reason"]
    for r in ("REMINDER_AS_ANCHOR", "REQUESTER_COMPLIANCE_ONLY", "MID_THREAD_REPLY", "NO_SUBSTANTIVE_REQUESTER_MSG"):
        assert reasons.get(r, 0) >= 1, r
    # KB-level invariants
    assert res.kb_report["score"] == 1.0
    ids = {c.case_id for c in res.canonical}
    for c in res.canonical:
        assert c.solution, c.case_id
        assert c.original_questions, c.case_id
        assert all(r in ids for r in c.related_case_ids + c.leads_to_case_ids)
        assert isinstance(c.escalation_flag, bool)
        assert c.member_thread_ids and c.evidence_msg_ids
    # sensitive topics always escalate
    assert all(c.escalation_flag for c in res.canonical if c.topic in cfg.sensitive_topics)
    # graph and traceability
    assert res.graph["_stats"]["nodes_by_label"]["Case"] == len(res.canonical)
    assert res.graph["_stats"]["edges_by_type"]["INSTANCE_OF"] == len(res.canonical)


def test_no_raw_pii_in_canonical_kb(synthetic_messages):
    from c2k.extract.anonymize import has_raw_volatile
    res = run_pipeline(synthetic_messages, config=PipelineConfig(known_names=NAMES))
    for c in res.canonical:
        text = " ".join([c.case, c.solution or ""] + c.original_questions)
        assert has_raw_volatile(text, NAMES) == [], (c.case_id, text[:120])
        assert "@" not in text


def test_retrieval_answers_and_escalates(synthetic_messages):
    res = run_pipeline(synthetic_messages, config=PipelineConfig(known_names=NAMES))
    llm = MockLLM()
    a = answer_question("wifi keeps dropping at my desk on the 3rd floor, what can I do?", res.index, llm, threshold=0.45)
    assert a.hits[0].case.topic == "wifi_access"
    assert a.based_on and a.based_on[0] == a.hits[0].case_id
    assert a.evidence and a.evidence[0]["threads"]
    a2 = answer_question("Can I bring my dog to the office?", res.index, llm, threshold=0.45)
    assert a2.escalate and a2.based_on == []
    a3 = answer_question("I lost my access card, what should I do?", res.index, llm, threshold=0.45)
    assert a3.lang == "en" and a3.hits[0].case.topic == "access_card" and a3.escalate   # sensitive topic


def test_validate_kb_reports_dangling_refs(synthetic_messages):
    res = run_pipeline(synthetic_messages, config=PipelineConfig(known_names=NAMES))
    res.canonical[0].related_case_ids.append("c-deadbeef")
    rep = validate_kb(res.canonical, set())
    assert rep["dangling_refs"] == [(res.canonical[0].case_id, "c-deadbeef")]
    assert rep["score"] < 1.0
