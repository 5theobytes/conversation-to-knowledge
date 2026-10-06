"""Merge each cluster into ONE canonical case.

Singletons are copied 1:1 without an LLM call. Multi-member clusters are sent
to the ``merge`` role (generalised case + one combined solution with
"Variant N" when methods differ + union of volatile kinds). Assembly of the
record (stable id, accumulated original questions, status, timestamps) is
deterministic.
"""
from __future__ import annotations

import hashlib
import json
import re

from ..cluster.cluster import Cluster
from ..extract.llm import LLMProvider
from ..extract.prompts import load_prompt
from ..models import CanonicalCase, RawCase

UNRESOLVED_FALLBACK = "Agent acknowledged the request; no concrete resolution within the thread slice."


def normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").strip().lower())


def stable_case_id(topic: str, case_text: str) -> str:
    return "c-" + hashlib.sha1(f"{topic}|{case_text}".encode("utf-8")).hexdigest()[:8]


def merge_clusters(clusters: list[Cluster], raws: list[RawCase], llm: LLMProvider) -> list[CanonicalCase]:
    by_id = {r.raw_id: r for r in raws}
    system = load_prompt("worker_cluster")
    out: list[CanonicalCase] = []
    for cl in clusters:
        members = [by_id[r] for r in cl.raw_ids if r in by_id]
        if not members:
            continue
        merged = None
        if len(members) >= 2:
            payload = {"topic": cl.topic, "inputs": [
                {"case": m.case, "solution": m.solution, "volatile_kinds": m.volatile_kinds, "status": m.status}
                for m in members]}
            merged = llm.complete_json(system, json.dumps(payload, ensure_ascii=False))
        out.append(assemble(cl, members, merged))
    return out


def assemble(cl: Cluster, members: list[RawCase], merged: dict | None) -> CanonicalCase:
    if merged is None:
        rep = max(members, key=lambda r: len(r.case or ""))
        case_text, solution = rep.case, rep.solution
        kinds = sorted({k for r in members for k in r.volatile_kinds})
    else:
        case_text = merged.get("case") or max(members, key=lambda r: len(r.case or "")).case
        solution = merged.get("solution")
        kinds = sorted(set(merged.get("volatile_kinds") or []))

    statuses = [r.status for r in members]
    if "resolved" in statuses:
        status = "resolved"
    elif "informational" in statuses:
        status = "informational"
    elif "escalated" in statuses:
        status = "escalated"
    else:
        status = "unresolved"
    if not solution:
        solution = UNRESOLVED_FALLBACK if status == "unresolved" else solution

    seen: set[str] = set()
    qrecs: list[dict] = []
    for r in sorted(members, key=lambda r: r.ts_first):
        k = normalize_question(r.original_question)
        if not k or k in seen:
            continue
        seen.add(k)
        qrecs.append({"text": r.original_question, "lang": r.original_question_lang,
                      "ts": r.ts_first, "thread_id": r.thread_id})

    cc = CanonicalCase(
        case_id=stable_case_id(cl.topic, case_text),
        topic=cl.topic, case=case_text, solution=solution, status=status,
        escalation_flag=any(r.escalation_flag for r in members),
        instances_count=len(members),
        first_seen_ts=min(r.ts_first for r in members), last_seen_ts=max(r.ts_last for r in members),
        volatile_kinds=kinds,
        original_questions=[q["text"] for q in qrecs], question_records=qrecs,
        raw_ids=[r.raw_id for r in members], member_thread_ids=[r.thread_id for r in members],
        evidence_msg_ids=sorted({m for r in members for m in r.evidence_msg_ids}),
        cluster_id=cl.cluster_id,
    )
    intents = {getattr(r, "_intent", None) for r in members} - {None}
    setattr(cc, "_intent", next(iter(intents)) if len(intents) == 1 else None)
    return cc
