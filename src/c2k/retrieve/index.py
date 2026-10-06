"""Retrieval index over canonical cases.

For each case we embed BOTH the canonical case text and every original
question separately (multiple vectors per case_id). Original phrasings are
the recall channel for slang / mixed-language input; results are deduplicated
by case_id so one case never appears twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..cluster.embed import Embedder, cosine
from ..models import CanonicalCase


@dataclass
class Hit:
    case_id: str
    cosine: float
    matched_via: str          # "case" | "question"
    matched_text: str
    case: CanonicalCase

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "cosine": round(self.cosine, 3), "matched_via": self.matched_via,
                "matched_text": self.matched_text, "topic": self.case.topic, "case": self.case.case,
                "solution": self.case.solution, "status": self.case.status,
                "escalation_flag": self.case.escalation_flag,
                "related_case_ids": self.case.related_case_ids, "leads_to_case_ids": self.case.leads_to_case_ids}


@dataclass
class CaseIndex:
    embedder: Embedder
    rows: list[tuple[str, str, str]] = field(default_factory=list)   # (case_id, kind, text)
    vectors: list[list[float]] = field(default_factory=list)
    cases: dict[str, CanonicalCase] = field(default_factory=dict)

    @classmethod
    def build(cls, cases: list[CanonicalCase], embedder: Embedder) -> "CaseIndex":
        idx = cls(embedder=embedder)
        for c in cases:
            idx.cases[c.case_id] = c
            idx.rows.append((c.case_id, "case", f"{c.topic} | {c.case}"))
            for q in c.original_questions:
                idx.rows.append((c.case_id, "question", q))
        idx.vectors = embedder.embed([r[2] for r in idx.rows])
        return idx

    def search(self, query: str, topk: int = 3) -> list[Hit]:
        qv = self.embedder.embed([query])[0]
        scored = sorted(((cosine(qv, v), i) for i, v in enumerate(self.vectors)), key=lambda x: (-x[0], x[1]))
        seen: set[str] = set()
        hits: list[Hit] = []
        for s, i in scored:
            cid, kind, text = self.rows[i]
            if cid in seen:
                continue
            seen.add(cid)
            hits.append(Hit(cid, s, kind, text, self.cases[cid]))
            if len(hits) >= topk:
                break
        return hits

    def expand(self, hits: list[Hit], per_hit: int = 2) -> list[CanonicalCase]:
        primary = {h.case_id for h in hits}
        extras: dict[str, CanonicalCase] = {}
        for h in hits:
            for cid in (h.case.related_case_ids[:per_hit] + h.case.leads_to_case_ids[:per_hit]):
                if cid in self.cases and cid not in primary:
                    extras[cid] = self.cases[cid]
        return list(extras.values())
