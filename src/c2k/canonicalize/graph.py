"""Case -> solution graph (JSON + idempotent Cypher export).

Schema:
    (:Case)-[:INSTANCE_OF]->(:Topic)
    (:Case)-[:RESOLVED_BY]->(:Solution)
    (:Case)-[:RELATED_TO]->(:Case)
    (:Case)-[:LEADS_TO]->(:Case)
    (:Case)-[:MENTIONS_VOLATILE]->(:VolatileKind)
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from ..models import CanonicalCase

LABEL_KEY = {"Case": "case_id", "Topic": "topic", "Solution": "sol_id", "VolatileKind": "kind"}


def build_graph(cases: list[CanonicalCase], preamble: str = "") -> dict[str, Any]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, props: dict) -> None:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "props": props}

    def edge(a: str, b: str, rel: str) -> None:
        edges.append({"from": a, "to": b, "type": rel})

    for t in sorted({c.topic for c in cases}):
        node(f"topic:{t}", "Topic", {"topic": t})
    for c in cases:
        node(f"case:{c.case_id}", "Case", {
            "case_id": c.case_id, "topic": c.topic, "case": c.case, "status": c.status,
            "escalation_flag": c.escalation_flag, "instances_count": c.instances_count,
            "first_seen_ts": c.first_seen_ts, "last_seen_ts": c.last_seen_ts,
        })
        edge(f"case:{c.case_id}", f"topic:{c.topic}", "INSTANCE_OF")
        if c.solution:
            sid = "s-" + hashlib.sha1(c.solution.encode("utf-8")).hexdigest()[:10]
            node(f"sol:{sid}", "Solution", {"sol_id": sid, "text": c.solution})
            edge(f"case:{c.case_id}", f"sol:{sid}", "RESOLVED_BY")
        for k in c.volatile_kinds:
            node(f"vol:{k}", "VolatileKind", {"kind": k})
            edge(f"case:{c.case_id}", f"vol:{k}", "MENTIONS_VOLATILE")
    ids = {c.case_id for c in cases}
    for c in cases:
        for rid in c.related_case_ids:
            if rid in ids:
                edge(f"case:{c.case_id}", f"case:{rid}", "RELATED_TO")
        for lid in c.leads_to_case_ids:
            if lid in ids:
                edge(f"case:{c.case_id}", f"case:{lid}", "LEADS_TO")

    stats = {
        "n_nodes": len(nodes), "n_edges": len(edges),
        "nodes_by_label": dict(Counter(n["label"] for n in nodes.values())),
        "edges_by_type": dict(Counter(e["type"] for e in edges)),
    }
    return {"_assistant_preamble": preamble, "_stats": stats, "nodes": list(nodes.values()), "edges": edges}


def _cyp(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_cyp(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    return f"'{s}'"


def to_cypher(graph: dict[str, Any]) -> str:
    lines = ["// Auto-generated case->solution graph (idempotent MERGE script)", ""]
    for label, key in LABEL_KEY.items():
        lines.append(f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE;")
    lines += ["", "// Nodes"]
    index: dict[str, tuple[str, Any]] = {}
    for n in graph["nodes"]:
        key = LABEL_KEY[n["label"]]
        kv = n["props"][key]
        index[n["id"]] = (n["label"], kv)
        rest = {k: v for k, v in n["props"].items() if k != key and v is not None}
        props = ", ".join(f"{k}: {_cyp(v)}" for k, v in rest.items())
        lines.append(f"MERGE (n:{n['label']} {{{key}: {_cyp(kv)}}})" + (f" SET n += {{{props}}};" if props else ";"))
    lines += ["", "// Edges"]
    for e in graph["edges"]:
        sl, skv = index[e["from"]]
        dl, dkv = index[e["to"]]
        lines.append(f"MATCH (a:{sl} {{{LABEL_KEY[sl]}: {_cyp(skv)}}}), (b:{dl} {{{LABEL_KEY[dl]}: {_cyp(dkv)}}}) "
                     f"MERGE (a)-[:{e['type']}]->(b);")
    return "\n".join(lines) + "\n"
