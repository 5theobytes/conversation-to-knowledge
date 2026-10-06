from c2k.canonicalize.graph import build_graph, to_cypher
from c2k.canonicalize.links import find_related, leads_candidates
from c2k.canonicalize.merge import assemble, stable_case_id
from c2k.canonicalize.utterances import build_utterance_index
from c2k.cluster.cluster import Cluster, cluster_cases
from c2k.cluster.embed import HashingEmbedder, cosine
from c2k.models import RawCase


def raw(rid, topic, case, from_id="u1", oq="how to fix wifi", ts=0, status="resolved", sol="Agent response: reconnect"):
    return RawCase(raw_id=rid, thread_id=f"c:{ts}", chat_id="c", from_id=from_id, topic=topic, case=case, solution=sol,
                   status=status, original_question=oq, original_question_lang="en", evidence_msg_ids=[ts], msg_ids=[ts],
                   ts_first=ts, ts_last=ts + 10, n_agent=1, n_requester=1, requester_text_len=40, escalation_flag=False)


def test_hashing_embedder_is_deterministic_and_normalized():
    e = HashingEmbedder()
    a, b = e.embed(["wifi keeps dropping on floor 3", "wifi keeps dropping on floor 3"])
    assert abs(cosine(a, b) - 1.0) < 1e-9
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    c = e.embed(["invoice shows a wrong amount"])[0]
    assert cosine(a, c) < 0.3


def test_cluster_within_topic_only():
    raws = [raw("r1", "wifi_access", "A member reports unstable wifi at their desk."),
            raw("r2", "wifi_access", "A member reports unstable wifi at their desk.", from_id="u2", ts=5),
            raw("r3", "printer_issue", "A member reports unstable wifi at their desk.", ts=9),   # same text, other topic
            raw("r4", "wifi_access", "A member asks for the guest wifi password.", ts=12)]
    cl = cluster_cases(raws, HashingEmbedder(), threshold=0.82)
    sizes = {c.cluster_id: sorted(c.raw_ids) for c in cl}
    assert sizes["wifi_access-001"] == ["r1", "r2"]
    assert len([c for c in cl if c.topic == "printer_issue"]) == 1
    assert any(c.raw_ids == ["r4"] for c in cl)


def test_cluster_same_requester_precondition():
    raws = [raw("r1", "wifi_access", "same text"), raw("r2", "wifi_access", "same text", from_id="u2", ts=5)]
    cl = cluster_cases(raws, HashingEmbedder(), threshold=0.82, require_same_requester=True)
    assert len(cl) == 2


def test_assemble_canonical_record():
    raws = [raw("r1", "wifi_access", "A member reports unstable wifi.", oq="wifi down", ts=0, status="unresolved", sol=None),
            raw("r2", "wifi_access", "A member reports unstable wifi.", oq="WIFI  down", ts=50),
            raw("r3", "wifi_access", "A member reports unstable wifi.", oq="internet keeps dropping", ts=100)]
    cc = assemble(Cluster("wifi_access-001", "wifi_access", ["r1", "r2", "r3"]), raws, None)
    assert cc.case_id == stable_case_id("wifi_access", "A member reports unstable wifi.")
    assert cc.instances_count == 3 and cc.status == "resolved"
    assert cc.original_questions == ["wifi down", "internet keeps dropping"]   # dedup on normalised text
    assert cc.first_seen_ts == 0 and cc.last_seen_ts == 110
    assert cc.member_thread_ids == ["c:0", "c:50", "c:100"]


def test_unresolved_singleton_gets_fallback_solution():
    r = raw("r1", "ac_temperature", "Too cold.", status="unresolved", sol=None)
    cc = assemble(Cluster("ac_temperature-001", "ac_temperature", ["r1"]), [r], None)
    assert cc.status == "unresolved" and "no concrete resolution" in cc.solution


def test_related_and_leads_candidates():
    e = HashingEmbedder()
    raws = [raw("r1", "wifi_access", "A member reports unstable wifi at their desk on floor three."),
            raw("r2", "wifi_access", "A member reports unstable wifi at their desk on floor two.", ts=5),
            raw("r3", "parking", "A member asks about parking.", ts=9)]
    cases = [assemble(Cluster(f"{r.topic}-00{i}", r.topic, [r.raw_id]), [r], None) for i, r in enumerate(raws, 1)]
    vecs = e.embed([f"{c.topic} | {c.case}" for c in cases])
    rel = find_related(cases, vecs, topk=3, min_cos=0.5)
    assert rel[cases[0].case_id] == [cases[1].case_id]
    assert cases[2].case_id not in rel[cases[0].case_id]
    pairs = leads_candidates(cases, vecs, lo=0.3, hi=0.99)
    assert pairs and {pairs[0][0], pairs[0][1]} == {0, 1}


def test_utterance_index_and_graph():
    raws = [raw("r1", "wifi_access", "A member reports unstable wifi.", oq="wifi down", ts=0),
            raw("r2", "wifi_access", "A member reports unstable wifi.", oq="wifi down", ts=5)]
    cc = assemble(Cluster("wifi_access-001", "wifi_access", ["r1", "r2"]), raws, None)
    cc.volatile_kinds = ["amount"]
    utt = build_utterance_index([cc])
    assert len(utt[cc.case_id]["utterances"]) == 1
    g = build_graph([cc], "preamble")
    assert g["_stats"]["nodes_by_label"] == {"Topic": 1, "Case": 1, "Solution": 1, "VolatileKind": 1}
    assert g["_stats"]["edges_by_type"] == {"INSTANCE_OF": 1, "RESOLVED_BY": 1, "MENTIONS_VOLATILE": 1}
    cy = to_cypher(g)
    assert "MERGE (n:Case {case_id:" in cy and "MERGE (a)-[:RESOLVED_BY]->(b)" in cy
