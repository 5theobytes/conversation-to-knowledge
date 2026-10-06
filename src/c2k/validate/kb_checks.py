"""Knowledge-base level validation (after canonicalization and linking).

Checks: dangling link targets, self-links, duplicate case ids, escalation
consistency for sensitive topics, meta-solutions ("agent handled it"),
unresolved cases with a non-fallback solution, cases without utterances.
Returns a report dict with a 0..1 score (1.0 = no violations).
"""
from __future__ import annotations

import re
from typing import Any

from ..models import CanonicalCase

META_SOLUTION_RE = re.compile(r"\b(handled the request|took action to address|responded with guidance|provided information or processed)\b", re.I)


def validate_kb(cases: list[CanonicalCase], sensitive_topics: set[str]) -> dict[str, Any]:
    ids = [c.case_id for c in cases]
    id_set = set(ids)
    report: dict[str, list[Any]] = {
        "duplicate_case_ids": [i for i in ids if ids.count(i) > 1],
        "dangling_refs": [], "self_links": [], "escalation_flag_topic_violations": [],
        "meta_solution_violations": [], "missing_utterances": [], "unresolved_with_solution": [],
    }
    for c in cases:
        for rid in c.related_case_ids + c.leads_to_case_ids:
            if rid not in id_set:
                report["dangling_refs"].append((c.case_id, rid))
            if rid == c.case_id:
                report["self_links"].append(c.case_id)
        if c.topic in sensitive_topics and not c.escalation_flag:
            report["escalation_flag_topic_violations"].append(c.case_id)
        if c.solution and META_SOLUTION_RE.search(c.solution):
            report["meta_solution_violations"].append(c.case_id)
        if not c.original_questions:
            report["missing_utterances"].append(c.case_id)
        if c.status == "unresolved" and c.solution and "no concrete resolution" not in c.solution:
            report["unresolved_with_solution"].append(c.case_id)
    n_viol = sum(len(v) for v in report.values())
    score = max(0.0, 1.0 - 0.05 * n_viol)
    return {"n_cases": len(cases), "n_violations": n_viol, "score": round(score, 3), **report}
