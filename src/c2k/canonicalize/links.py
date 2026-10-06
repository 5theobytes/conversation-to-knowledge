"""RELATED_TO and LEADS_TO links between canonical cases.

RELATED_TO: top-K nearest canonical cases by cosine over "topic | case",
            cosine >= ``related_min`` (deterministic).
LEADS_TO:   candidate pairs in the SAME topic with cosine in [lo, hi) are
            sent to the ``leads_to`` role ("is B a continuation of A?"),
            both directions. Conservative by design: false positives create
            noisy chains.
"""
from __future__ import annotations

import json
from collections import defaultdict

from ..cluster.embed import Embedder, cosine
from ..extract.llm import LLMProvider
from ..extract.prompts import load_prompt
from ..models import CanonicalCase

RELATED_TOPK = 3
RELATED_MIN = 0.65
LEADS_LO = 0.55
LEADS_HI = 0.80


def find_related(cases: list[CanonicalCase], vecs: list[list[float]], topk: int = RELATED_TOPK,
                 min_cos: float = RELATED_MIN) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, c in enumerate(cases):
        scored = [(cosine(vecs[i], vecs[j]), cases[j].case_id) for j in range(len(cases)) if j != i]
        scored.sort(key=lambda x: (-x[0], x[1]))
        out[c.case_id] = [cid for s, cid in scored[:topk] if s >= min_cos]
    return out


def leads_candidates(cases: list[CanonicalCase], vecs: list[list[float]], lo: float = LEADS_LO,
                     hi: float = LEADS_HI) -> list[tuple[int, int, float]]:
    by_topic: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cases):
        by_topic[c.topic].append(i)
    pairs: list[tuple[int, int, float]] = []
    for idxs in by_topic.values():
        for a_pos in range(len(idxs)):
            for b_pos in range(a_pos + 1, len(idxs)):
                a, b = idxs[a_pos], idxs[b_pos]
                s = cosine(vecs[a], vecs[b])
                if lo <= s < hi:
                    pairs.append((a, b, s))
    pairs.sort(key=lambda p: -p[2])
    return pairs


def build_links(cases: list[CanonicalCase], embedder: Embedder, llm: LLMProvider | None,
                related_min: float = RELATED_MIN, leads_lo: float = LEADS_LO, leads_hi: float = LEADS_HI,
                max_pairs: int = 200) -> None:
    """Populate related_case_ids / leads_to_case_ids in place."""
    vecs = embedder.embed([f"{c.topic} | {c.case}" for c in cases])
    related = find_related(cases, vecs, min_cos=related_min)
    for c in cases:
        c.related_case_ids = related.get(c.case_id, [])
        c.leads_to_case_ids = []
    if llm is None:
        return
    system = load_prompt("worker_links")
    for a, b, _s in leads_candidates(cases, vecs, leads_lo, leads_hi)[:max_pairs]:
        for x, y in ((a, b), (b, a)):
            payload = {"case_a": _view(cases[x]), "case_b": _view(cases[y])}
            r = llm.complete_json(system, json.dumps(payload, ensure_ascii=False))
            if str(r.get("answer", "")).upper().startswith("YES"):
                cases[x].leads_to_case_ids.append(cases[y].case_id)


def _view(c: CanonicalCase) -> dict:
    return {"case_id": c.case_id, "topic": c.topic, "case": c.case, "solution": c.solution,
            "intent": getattr(c, "_intent", None)}
