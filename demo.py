"""Offline end-to-end demo.

    python demo.py [--data demo_data/synthetic_messages.jsonl] [--out out/demo]

Loads the synthetic corpus, reconstructs threads, extracts cases with the
MockLLM, clusters, validates, builds the graph and answers three sample
questions with the retrieval layer, printing an evidence trail for each.
No network, no API keys, stdlib only.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from c2k.cluster.embed import HashingEmbedder  # noqa: E402
from c2k.extract.llm import MockLLM  # noqa: E402
from c2k.ingest.loader import load_messages  # noqa: E402
from c2k.normalize.sessions import cut_sessions  # noqa: E402
from c2k.pipeline import PipelineConfig, run_pipeline  # noqa: E402
from c2k.retrieve.answer import answer_question  # noqa: E402

ROOT = Path(__file__).resolve().parent
KNOWN_NAMES = ["Mira Okonkwo", "Dariusz Lind", "Ananya Pillai", "Tomas Vega", "Zhanna Kirilenko", "Rustam Aliyev",
               "Vera Tsoi", "Niran Chaiya", "Pimchan Suwan", "Kiet Boonmee", "Ilse Varga", "Bao Nguyen",
               "Keiko Arai", "Omar Haddad"]
SAMPLE_QUESTIONS = [
    "wifi keeps dropping at my desk on the 3rd floor, what can I do?",
    "I lost my access card, what should I do?",
    "ค่าสมาชิกรายเดือนตัดวันไหนคะ",
    "Can I bring my dog to the office?",
]


def banner(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "demo_data" / "synthetic_messages.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "out" / "demo"))
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    banner("1. INGEST + THREAD RECONSTRUCTION")
    messages = load_messages(args.data)
    print(f"messages: {len(messages)}  chats: {len({m.chat_id for m in messages})}  "
          f"langs: {sorted({m.lang for m in messages})}")
    sessions, s_drops = cut_sessions(messages)
    print(f"sessions (12h gap + dyad rule): {len(sessions)}, dropped: {[d.reason for d in s_drops]}")

    llm = MockLLM()
    embedder = HashingEmbedder()
    # Thresholds are embedder-specific. The production values (0.82 cluster / 0.65 related /
    # 0.55 answer) were tuned for multilingual sentence embeddings; the stdlib hashing
    # embedder scores paraphrases lower, so the link and answer cut-offs are relaxed here.
    cfg = PipelineConfig(known_names=KNOWN_NAMES, cluster_threshold=0.82, related_min=0.5, leads_lo=0.3)
    answer_threshold = 0.45
    result = run_pipeline(messages, llm=llm, embedder=embedder, config=cfg)
    print(f"threads: {len(result.threads)} (substantive: {sum(t.has_substantive_requester_msg for t in result.threads)})")

    banner("2. PRE-QUALIFY + EXTRACT (MockLLM) + POST-FILTER")
    st = result.stats()
    print(f"raw cases: {st['raw_cases']}  after post-filter: {st['raw_after_post_filter']}")
    print("drops by stage :", st["drops_by_stage"])
    print("drops by reason:", st["drops_by_reason"])
    if result.rule_drops:
        d, v = result.rule_drops[0]
        print(f"example rule drop -> {v.reason}")

    banner("3. CLUSTER + MERGE -> CANONICAL CASES")
    print(f"canonical cases: {st['canonical_cases']}  topics: {st['topics']}")
    for c in sorted(result.canonical, key=lambda c: (c.topic, -c.instances_count))[:8]:
        print(f"- {c.case_id} [{c.topic}] x{c.instances_count} status={c.status} esc={c.escalation_flag} "
              f"langs={sorted({q['lang'] for q in c.question_records})}")
        print(f"    case:     {c.case[:110]}")
        print(f"    solution: {(c.solution or '')[:110]}")
    print("  ...")

    banner("4. VALIDATE (KB checks) + GRAPH")
    print(f"kb score: {result.kb_report['score']}  violations: {result.kb_report['n_violations']}")
    print(f"graph: {result.graph['_stats']}")
    chains = [(c.case_id, c.leads_to_case_ids) for c in result.canonical if c.leads_to_case_ids]
    print(f"LEADS_TO chains: {chains[:3]}")

    banner(f"5. ANSWER SAMPLE QUESTIONS (retrieval + MockLLM, similarity threshold {answer_threshold})")
    for q in SAMPLE_QUESTIONS:
        a = answer_question(q, result.index, llm, threshold=answer_threshold)
        print(a.render())
        print("-" * 78)

    if not args.no_write:
        result.write(args.out)
        print(f"\nartifacts written to {args.out}/ (threads, cases_raw, cases_canonical, trash, graph.json, import.cypher, kb_report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
