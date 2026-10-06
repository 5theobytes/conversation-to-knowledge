# Pipeline architecture

This document describes the production pipeline this repository is a sanitized
reference implementation of, stage by stage, and says honestly for each stage
what is deterministic code, what is an LLM call, and what is a heuristic that
was calibrated against one client's data.

Two pipeline shapes existed in the production project:

* **the multi-agent pipeline** (the one that produced the final knowledge base;
  21+ supervised iterations, 38/38 regression tests at freeze) — this is what
  `src/c2k` and `demo.py` reproduce;
* **a simplified sequential variant** (sessions instead of threads, one model
  per stage, Russian-language output) — only its deterministic session cutter
  is ported (`normalize/sessions.py`).

## Stage map

```
 raw chat export (JSONL)
        │
        ▼
 ┌─────────────────┐  deterministic
 │ 1. ingest       │  role assignment: explicit from_role, else "active in >=2 chats => agent"
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐  deterministic (regex + time gaps)
 │ 2. normalize    │  language by script; chatter detection (ack / greeting / emoji);
 │    threads      │  requester-driven thread reconstruction (12h hard gap, 30min-after-ack soft gap,
 │    sessions     │  agent cannot open a thread); alt: 12h sessions + dyad rule
 └─────────────────┘
        │  threads with >=1 substantive requester message
        ▼
 ┌─────────────────┐  LLM, one call per thread, parallel, fresh context
 │ 3. needs_help   │  "is there a requester who really needs help?"  -> gate + topic hint
 └─────────────────┘  + sensitive_topic_signal (forces escalation downstream)
        │  needs_help=true
        ▼
 ┌─────────────────┐  LLM, per thread
 │ 4. extract      │  0..N sub-cases: topic, case (requester situation), solution (agent action),
 └─────────────────┘  status, original_question (verbatim, original language), evidence ids,
        │             volatile placeholders, escalation_flag
        ▼
 ┌─────────────────┐  deterministic rule engine (ordered, first failure drops, every drop logged)
 │ 5. post-filter  │  18 rules ported here (26-27 in production), each with a named driver error
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐  deterministic: embeddings + union-find within topic (cosine >= 0.82)
 │ 6. cluster      │  optional same-requester precondition
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐  LLM only for clusters of size >= 2; singletons copied 1:1
 │ 7. merge        │  canonical case + one combined solution ("Variant N") + volatile kinds;
 └─────────────────┘  record assembly (stable id, question records, status, timestamps) is code
        │  canonical records re-pass the rule engine
        ▼
 ┌─────────────────┐  RELATED_TO: deterministic top-3 cosine >= 0.65
 │ 8. links        │  LEADS_TO: candidate pairs (same topic, cosine 0.55..0.80) -> LLM yes/no, both directions
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐  deterministic
 │ 9. utterances   │  original-language phrasings per case, dedup, earliest ts, never translated
 │    kb checks    │  dangling refs, self-links, escalation consistency, meta-solutions
 │    graph        │  Case / Topic / Solution / VolatileKind nodes; JSON + idempotent Cypher
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐  deterministic retrieval + LLM answer
 │ 10. retrieve    │  index = case text + every original question; dedupe by case; expand links;
 │     answer      │  cosine < 0.55 => "no confirmed solution, escalate"; escalation_flag honoured;
 └─────────────────┘  reply carries case ids -> thread ids -> message ids (evidence trail)
```

In production the loop around stages 3-9 was supervised: a **judge** re-read
every source thread and scored each emitted case (structural 1-5 x5 +
eyeball verdict), **advisors** proposed fixes, and a **supervisor** decided per
error class whether the fix belonged in a worker prompt, in the rule engine,
or was a data problem. Those three roles are documented in `agents/` but not
executed by the offline demo.

## Per-stage detail

### 1. Ingest (`src/c2k/ingest`)
Deterministic. Production additionally classified chats by title into buckets
(individual support / group workplace / internal) and treated senders active in
internal chats as agents. The bucket logic was company-specific and is not
ported; the ">= 2 chats => agent" heuristic is.

### 2. Normalize (`src/c2k/normalize`)
Deterministic. `lang.py` detects Thai and Cyrillic by script and falls back to
`en`; production also had marker-word lists for one more Latin-script language.
`threads.py` is a near-verbatim port of the production thread builder (the
version that replaced an earlier "split on 12h gap only" approach after it
glued unrelated questions together). `sessions.py` ports the sequential
variant's 12h + dyad cutter. Production also had a language filter (drop
threads whose requester wrote 100% in the agents' native language); the helper
`is_all_cyrillic` is kept, the filter is not applied in the demo.

### 3. needs_help pre-qualifier (`agents/worker_needs_help.md`)
LLM (production: a small fast model, one call per thread). Introduced late
(iteration 24) after analysis showed most judge errors were threads that should
never have reached extraction. The decision taxonomy (`AGENT_INITIATED`,
`REQUESTER_COMPLIANCE_ONLY`, `REMINDER_AS_ANCHOR`, `MID_THREAD_REPLY`,
`TOO_THIN`, ...) is ported verbatim in spirit; the `MockLLM` implements it with
regexes.

### 4. Extract (`agents/worker_extract.md`)
LLM. The prompt in `agents/` is a generic rewrite of a ~300-line production
memory file. Rules that survived 20+ iterations and are kept: anchor
realignment, mid-thread guard, last-resolution-turn as solution, banned holding
acks, fabrication ban (original_question must be a substring of a requester
message), strict case/solution split, evidence completeness, escalation
criteria, anonymisation hard rule. Dropped as company-specific: topic
sub-taxonomy, bank/brand lists, name blocklists, geographic literals.

The `MockLLM` extractor is a keyword lexicon (`extract/lexicon.py`) plus the
deterministic scrubber (`extract/anonymize.py`). It writes template English
case descriptions, takes the last non-holding agent turn as the solution, and
does not translate. It is a stand-in to run the rest of the pipeline, not a
model.

### 5. Post-filter rule engine (`src/c2k/validate`)
Deterministic. Production ended with 26-27 active rules (plus ~15 disabled but
retained ones) after 21 iterations; each carried the iteration it came from and
the error case that drove it. Ported (18): greeting-as-case, holding-ack
solution, topic=other dump, requester-compliance solution, case contains agent
action (active + passive voice), PII leak (phones / cards / amounts / e-mails /
dates / names from context), no-solution-without-unresolved, fabricated
document solution, trivial anchor without keyword, reminder as anchor,
mid-thread reaction, agent-triggered reactive clarification, evidence ids
incomplete, missing escalation flag, wrong escalation flag for sensitive topic,
composite multi-topic, date leak despite declaration, original-question
grounding (token-run match against requester messages). Not ported:
bank-brand regexes, named-person blocklists, topic-keyword contradiction
tables, geographic literal list, paraphrase-vs-raw-action lookup (needs the
raw extraction file), agent-proactive financial offer detector.

Lesson recorded in the production notes and kept in `engine.py`'s docstring:
the filter is a safety net; if it drops half of the output, the prompt is
wrong.

### 6. Cluster (`src/c2k/cluster`)
Deterministic. Production used a local multilingual sentence-embedding model
and FAISS; this port uses a stdlib hashing embedder by default (word + char
3-gram, signed hashing, L2-normalised) and offers a `SentenceTransformerEmbedder`
adapter. Union-find within topic at cosine >= 0.82 is ported as is. The
same-requester merge precondition (added after cross-person merges leaked
context) is available as a flag.

### 7. Merge (`agents/worker_cluster.md`)
LLM for multi-member clusters; record assembly is code (`canonicalize/merge.py`,
ported). Stable id = sha1(topic | case text). Status precedence resolved >
informational > escalated > unresolved. Unresolved cases get a literal fallback
sentence rather than null (production rule `STRICT_NULL_SOLUTION_BAN`).

### 8. Links (`canonicalize/links.py`, `agents/worker_links.md`)
RELATED_TO deterministic (ported). LEADS_TO LLM-judged on candidate pairs
(ported: candidate selection, both-direction asking, pair cap). The mock judge
uses a small chain table.

### 9. Utterances, KB checks, graph (`canonicalize/`, `validate/kb_checks.py`)
Deterministic, ported. The graph schema and the idempotent Cypher export match
production; the "assistant preamble" (volatile-data rules) is embedded in
`graph.json`. Production additionally exported a flat CSV/Markdown table.

### 10. Retrieval and answer (`src/c2k/retrieve`, `agents/answer.md`)
Index construction (case text + every original question, dedupe by case id)
and context expansion through RELATED_TO / LEADS_TO are ported. The hard
rules (cosine < 0.55 => escalate; unresolved => escalate; escalation_flag =>
human must confirm) are enforced in code, not only in the prompt. The
production answer model was a larger model than the extraction model, on the
argument that one wrong user-facing answer costs more than a few cents.

## Data models (`src/c2k/models.py`)
`Message` -> `Thread` / `Session` -> `NeedsHelpVerdict` -> `RawCase` ->
`CanonicalCase` (+ `DropRecord` for every negative decision). Field names were
neutralised (`requester` / `agent` instead of the client's roles).

## Escalation rule (unchanged from production)
`escalation_flag = true` when answering needs: access to the requester's
personal records; specific data from the requester; approval or action beyond
a support agent's authority; a transaction or state change. `false` only when
the answer is a generic instruction. Sensitive topics are always `true`,
enforced twice (pre-qualifier signal + rule engine).

## Thresholds
| parameter | production (multilingual embeddings) | demo (hashing embedder) |
|---|---|---|
| cluster cosine | 0.82 | 0.82 (templates are identical) |
| RELATED_TO min | 0.65 | 0.50 |
| LEADS_TO window | 0.55..0.80 | 0.30..0.80 |
| answer threshold | 0.55 | 0.45 |

Thresholds are properties of the embedder, not of the pipeline.
