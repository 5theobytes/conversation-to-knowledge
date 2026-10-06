"""Grounded answer with an evidence trail.

retrieve top-K -> expand RELATED_TO / LEADS_TO -> ask the ``answer`` role.
Hard rules (enforced here, not only in the prompt):
* top-1 cosine below ``threshold`` -> no answer, escalate to a human;
* unresolved case -> say so, escalate;
* the reply always carries the case_ids it relied on and, through them,
  the thread ids and message ids the case was built from. That is the audit
  trail: every sentence in the KB can be traced back to raw messages.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..extract.llm import LLMProvider
from ..extract.prompts import load_prompt
from ..normalize.lang import detect_lang
from .index import CaseIndex, Hit

SIMILARITY_THRESHOLD = 0.55


@dataclass
class Answer:
    query: str
    lang: str
    text: str
    escalate: bool
    based_on: list[str]
    hits: list[Hit]
    context_cases: list[str]
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"Q ({self.lang}): {self.query}", f"A: {self.text}", f"escalate_to_human: {self.escalate}",
                 "evidence trail:"]
        if not self.hits:
            lines.append("  (no hits)")
        for h in self.hits:
            lines.append(f"  - {h.case_id} [{h.case.topic}] cosine={h.cosine:.3f} via={h.matched_via} status={h.case.status} "
                         f"escalation_flag={h.case.escalation_flag}")
            lines.append(f"      matched: {h.matched_text[:90]}")
            lines.append(f"      threads: {h.case.member_thread_ids}  evidence_msg_ids: {h.case.evidence_msg_ids}")
        if self.context_cases:
            lines.append(f"  context (related/leads_to): {self.context_cases}")
        lines.append(f"  based_on: {self.based_on}")
        return "\n".join(lines)


def answer_question(query: str, index: CaseIndex, llm: LLMProvider, topk: int = 3,
                    threshold: float = SIMILARITY_THRESHOLD) -> Answer:
    lang = detect_lang(query)
    hits = index.search(query, topk=topk)
    extras = index.expand(hits)
    system = load_prompt("answer")
    payload = {"query": query, "lang": lang, "threshold": threshold,
               "hits": [h.to_dict() for h in hits],
               "context": [{"case_id": c.case_id, "topic": c.topic, "case": c.case, "solution": c.solution} for c in extras]}
    r = llm.complete_json(system, json.dumps(payload, ensure_ascii=False))
    escalate = bool(r.get("escalate"))
    if not hits or hits[0].cosine < threshold:
        escalate = True  # enforced regardless of what the model says
    based_on = [cid for cid in (r.get("based_on") or []) if cid in index.cases]
    evidence = [{"case_id": h.case_id, "threads": h.case.member_thread_ids, "evidence_msg_ids": h.case.evidence_msg_ids}
                for h in hits if h.case_id in based_on]
    return Answer(query, lang, r.get("answer", ""), escalate, based_on, hits, [c.case_id for c in extras], evidence)
