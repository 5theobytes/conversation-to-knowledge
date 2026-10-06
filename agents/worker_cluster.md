<!-- task: merge -->
# worker_cluster — merge one cluster of near-duplicate sub-cases into a canonical record

## Input
`{"topic": "...", "inputs": [{"case", "solution", "volatile_kinds", "status"}, ...]}` —
N descriptions of the SAME type of situation (same topic, similar context).

## Output (one JSON object, no commentary)
```json
{"case": "3-5 English sentences. Generalised situation: what typically happens, what the agent usually clarifies, what is usually discovered. Anonymised, placeholders only.",
 "solution": "3-5 English sentences. ONE combined recipe. If inputs show distinct methods: 'Variant 1: ...', 'Variant 2: ...'.",
 "volatile_kinds": ["union of placeholder kinds"]}
```

## Rules
- Merge, do not pick: the canonical case covers every member.
- Cross-instance consistency: members must share topic, compatible solutions and a primary
  status. If solutions contradict ("agent approved" vs "agent denied") they are different
  cases: return the majority and flag the rest (`"split": [...]`).
- Composite detection: if the merged description would exceed ~150 words AND span 3+
  unrelated domains, do not merge; split into atomic records.
- Same-requester precondition (production setting): merging across different people is only
  allowed when the deployment has confirmed it does not leak personal context.
- Paraphrase grounding and the strict case/solution split still apply.
- Solution is never null/empty; unresolved -> literal fallback sentence.
- Keep `original_questions` and their records; they are the retrieval recall channel.
- Scrub again: if any member leaked an amount, name or date, fix it at canonical level.
