# conversation-to-knowledge

**A pipeline for turning noisy multilingual operational conversations into a
validated, traceable knowledge base for search, analytics and AI assistants.**

Status: **sanitized reference implementation**. The production system was
built for a client on confidential chat data; this repository re-implements
its deterministic core on a synthetic, neutral domain (a coworking space's
member support), with LLM calls behind a provider interface and an offline
mock so everything runs with no API keys and no third-party packages.

## The problem

Operational support happens in chat: members, employees or customers write in
whatever language they speak, support staff answer, and the resolution is
buried between greetings, reminders, "sent, please check" and three
follow-ups. The knowledge in those threads is real but unusable: it cannot be
searched, counted, or given to an assistant without leaking personal data or
inventing answers.

The hard parts are not the model calls. They are:

* deciding what a "question" is (most threads are not one);
* not letting the model fabricate a solution when the agent only said "let me check";
* keeping names, numbers, dates and account details out of the output;
* merging the same situation asked five ways in three languages into one record;
* knowing when an assistant must stop and hand over to a human;
* being able to point from any sentence in the knowledge base back to the raw messages.

## Pipeline

```
 chat export ─► ingest ─► threads ─► needs_help? ─► extract ─► post-filter ─► cluster ─► merge
                (code)     (code)      (LLM)         (LLM)     (18 rules)     (code)   (LLM, size>=2)
                                                                                         │
      answer ◄─ retrieve ◄─ graph ◄─ KB checks ◄─ utterances ◄─ links (RELATED_TO code, LEADS_TO LLM)
       (LLM)      (code)    (code)     (code)        (code)
```

Every negative decision at every stage is logged with a stage and a reason;
every canonical case keeps its thread ids and message ids. See
[`architecture/PIPELINE.md`](architecture/PIPELINE.md) for the stage-by-stage
description of what is deterministic, what is a model call, and what was a
calibrated heuristic.

## Quickstart

```bash
git clone <this repo> && cd conversation-to-knowledge
python -m pip install pytest            # the pipeline itself is stdlib-only
python scripts/make_synthetic.py        # regenerate demo_data/ (seeded, reproducible)
python demo.py                          # offline end-to-end run, writes out/demo/
python -m pytest -q                     # 40 tests
```

Python 3.11+. To plug in a real model, implement `LLMProvider` (or use the
`AnthropicLLM` adapter in `src/c2k/extract/llm.py`) and pass it to
`run_pipeline`; to use real multilingual embeddings, pass
`SentenceTransformerEmbedder()` from `src/c2k/cluster/embed.py`.

```python
from c2k.ingest import load_messages
from c2k.pipeline import run_pipeline, PipelineConfig
from c2k.retrieve import answer_question

res = run_pipeline(load_messages("demo_data/synthetic_messages.jsonl"),
                   config=PipelineConfig(known_names=[...]))
print(answer_question("wifi keeps dropping at my desk", res.index, llm=...).render())
```

## Demo output

Run `python demo.py` to reproduce the offline English/Thai example.
The current full output is in [`examples/demo_output.txt`](examples/demo_output.txt).

## What the knowledge base looks like

One canonical case:

```json
{
  "case_id": "c-80531f6a",
  "topic": "access_card",
  "case": "A member lost their access card and asks to block it and issue a replacement.",
  "solution": "Agent response: Old card is blocked. A replacement is ready at reception, bring your ID; the replacement fee of <amount> will be added to your next invoice.",
  "status": "resolved",
  "escalation_flag": true,
  "instances_count": 2,
  "first_seen_ts": 1900201470,
  "last_seen_ts": 1901197365,
  "volatile_kinds": [
    "amount",
    "card"
  ],
  "original_questions": [
    "I lost my access card somewhere yesterday, card number <card_number>. Can you block it and issue a new one?"
  ],
  "question_records": [
    {
      "text": "I lost my access card somewhere yesterday, card number <card_number>. Can you block it and issue a new one?",
      "lang": "en",
      "ts": 1900201470,
      "thread_id": "chat-m-04:1012"
    }
  ],
  "raw_ids": [
    "r-fc819c21c6",
    "r-d91c2f989c"
  ],
  "member_thread_ids": [
    "chat-m-04:1012",
    "chat-m-06:1116"
  ],
  "evidence_msg_ids": [
    1012,
    1013,
    1014,
    1117,
    1118,
    1119
  ],
  "cluster_id": "access_card-001",
  "related_case_ids": [],
  "leads_to_case_ids": []
}
```

`escalation_flag` is the contract with any assistant built on top: `true`
means a human must confirm or act (personal records, data from the requester,
authority, state change); `false` means the solution is a generic instruction.

## Metrics (reported, from the confidential client project)

These numbers come from the production run on the client's data and cannot
be reproduced from this repository:

* 38/38 regression tests passing on the frozen rule set (iteration 21);
* 228 canonical cases in the final production knowledge base, built from
  13,781 raw chat messages in four languages (an earlier baseline run of the
  pipeline produced 303 cases across 32 topics; the final base came from a
  simplified pipeline plus 564 logged human edits);
* precision was measured per iteration by an independent judge model
  re-reading every source thread. The judge reported no errors on the
  in-loop evaluation slice but flagged 20 of 53 cases on fresh threads, which
  is why the pipeline was simplified and human review was added. No overall
  accuracy figure is claimed here: the final base was not independently
  evaluated and the evaluation set was small and client-specific.

What this repository demonstrates instead: 40 unit and end-to-end tests on
the deterministic modules, and an offline run that drops the planted noise
threads for the right reasons and keeps raw personal data out of every record.

## What is NOT included

* The client's data, chat exports, case tables, prompts' domain sections,
  name/brand blocklists, topic taxonomy and iteration logs.
* The supervised improvement loop (judge, advisors, supervisor): the roles are
  documented in `agents/` but no orchestrator runs them here.
* Real model calls and real multilingual embeddings: adapters exist, the demo
  uses a keyword mock and a hashing embedder (no cross-lingual matching).
* 8-9 production post-filter rules that were domain-specific (bank brands,
  named persons, topic contradiction tables, geographic literals,
  raw-action paraphrase lookup).
* The flat CSV/Markdown exports and the Neo4j import tooling beyond the
  generated Cypher script.

## Layout

```
agents/           role prompts (needs_help, extract, cluster/merge, links, answer, judge, supervisor)
architecture/     PIPELINE.md
demo_data/        synthetic_messages.jsonl (seeded, invented names, EN/TH)
examples/         demo output and sample artifacts
scripts/          make_synthetic.py
src/c2k/          ingest · normalize · extract · cluster · canonicalize · validate · retrieve · pipeline
tests/            pytest
demo.py
```

## License

MIT.
