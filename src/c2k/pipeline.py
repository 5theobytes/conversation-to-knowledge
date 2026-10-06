"""End-to-end orchestration.

messages -> threads -> needs_help -> extract -> post-filter -> cluster ->
merge -> links -> utterances -> KB checks -> graph -> retrieval index.

Every stage's drops are collected in ``PipelineResult.drops`` (stage, key,
reason), which is the audit log the production run used for recall analysis.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonicalize.graph import build_graph, to_cypher
from .canonicalize.links import build_links
from .canonicalize.merge import merge_clusters
from .canonicalize.utterances import build_utterance_index
from .cluster.cluster import cluster_cases
from .cluster.embed import Embedder, HashingEmbedder
from .extract import lexicon
from .extract.llm import LLMProvider, MockLLM
from .extract.stages import run_extract, run_needs_help
from .io import write_jsonl
from .models import CanonicalCase, DropRecord, Message, RawCase, Thread
from .normalize.threads import build_threads
from .retrieve.index import CaseIndex
from .validate.engine import RuleContext, RuleEngine
from .validate.kb_checks import validate_kb
from .validate.rules import default_engine

ASSISTANT_PREAMBLE = (
    "Knowledge-base consumers: values rendered as <placeholders> were real at capture time but are volatile. "
    "Never quote a placeholder as a current fact; ask the requester for their own value. Cases with "
    "escalation_flag=true require a human agent to confirm or act. Reply in the requester's language."
)


@dataclass
class PipelineConfig:
    cluster_threshold: float = 0.82
    related_min: float = 0.65
    leads_lo: float = 0.55
    leads_hi: float = 0.80
    require_same_requester_for_merge: bool = False
    known_names: list[str] = field(default_factory=list)
    sensitive_topics: set[str] = field(default_factory=lambda: set(lexicon.SENSITIVE_TOPICS))
    substantive_keywords: list[str] = field(default_factory=lambda: sorted({k for ks in lexicon.TOPIC_KEYWORDS.values() for k in ks}))


@dataclass
class PipelineResult:
    messages: list[Message]
    threads: list[Thread]
    raw_cases: list[RawCase]
    filtered_raw: list[RawCase]
    canonical: list[CanonicalCase]
    utterances: dict[str, dict]
    graph: dict[str, Any]
    kb_report: dict[str, Any]
    drops: list[DropRecord]
    index: CaseIndex
    rule_drops: list[tuple[dict, Any]]

    def stats(self) -> dict[str, Any]:
        return {
            "messages": len(self.messages), "threads": len(self.threads),
            "threads_substantive": sum(1 for t in self.threads if t.has_substantive_requester_msg),
            "raw_cases": len(self.raw_cases), "raw_after_post_filter": len(self.filtered_raw),
            "canonical_cases": len(self.canonical), "topics": len({c.topic for c in self.canonical}),
            "drops_by_stage": _count(self.drops, "stage"), "drops_by_reason": _count(self.drops, "reason"),
            "graph": self.graph["_stats"], "kb_score": self.kb_report["score"],
        }

    def write(self, out_dir: str | Path) -> None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(out / "threads.jsonl", (t.to_dict() for t in self.threads))
        write_jsonl(out / "cases_raw.jsonl", (r.to_dict() for r in self.raw_cases))
        write_jsonl(out / "cases_canonical.jsonl", (c.to_dict() for c in self.canonical))
        write_jsonl(out / "trash.jsonl", (d.to_dict() for d in self.drops))
        (out / "utterances_by_case.json").write_text(json.dumps(self.utterances, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "graph.json").write_text(json.dumps(self.graph, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "import.cypher").write_text(to_cypher(self.graph), encoding="utf-8")
        (out / "kb_report.json").write_text(json.dumps(self.kb_report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "stats.json").write_text(json.dumps(self.stats(), ensure_ascii=False, indent=2), encoding="utf-8")


def _count(drops: list[DropRecord], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in drops:
        k = getattr(d, key)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def run_pipeline(messages: list[Message], llm: LLMProvider | None = None, embedder: Embedder | None = None,
                 engine: RuleEngine | None = None, config: PipelineConfig | None = None) -> PipelineResult:
    llm = llm or MockLLM()
    embedder = embedder or HashingEmbedder()
    engine = engine or default_engine()
    cfg = config or PipelineConfig()
    drops: list[DropRecord] = []
    by_id = {m.msg_id: m for m in messages}

    threads = build_threads(messages)
    verdicts = run_needs_help(threads, by_id, llm, drops)
    raws = run_extract(threads, verdicts, by_id, llm, drops, known_names=cfg.known_names)

    ctx = RuleContext(messages=by_id, known_names=cfg.known_names, sensitive_topics=cfg.sensitive_topics,
                      substantive_keywords=cfg.substantive_keywords)
    kept: list[RawCase] = []
    rule_drops: list[tuple[dict, Any]] = []
    for r in raws:
        v = engine.evaluate(r.to_dict(), ctx)
        if v.keep:
            kept.append(r)
        else:
            rule_drops.append((r.to_dict(), v))
            drops.append(DropRecord("post_filter", r.raw_id, v.failed_rule or "rule", v.reason))

    clusters = cluster_cases(kept, embedder, cfg.cluster_threshold, cfg.require_same_requester_for_merge)
    canonical = merge_clusters(clusters, kept, llm)
    # canonical records pass the same engine (merge can re-introduce leaks)
    final: list[CanonicalCase] = []
    for c in canonical:
        d = c.to_dict()
        d.update({"n_agent": 0, "msg_ids": c.evidence_msg_ids, "requester_text_len": 100})
        v = engine.evaluate(d, ctx)
        if v.keep:
            final.append(c)
        else:
            rule_drops.append((d, v))
            drops.append(DropRecord("post_filter_canonical", c.case_id, v.failed_rule or "rule", v.reason))
    build_links(final, embedder, llm, cfg.related_min, cfg.leads_lo, cfg.leads_hi)
    utterances = build_utterance_index(final)
    kb_report = validate_kb(final, cfg.sensitive_topics)
    graph = build_graph(final, ASSISTANT_PREAMBLE)
    index = CaseIndex.build(final, embedder)
    return PipelineResult(messages, threads, raws, kept, final, utterances, graph, kb_report, drops, index, rule_drops)
