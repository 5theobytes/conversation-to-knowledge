<!-- task: leads_to -->
# worker_links — LEADS_TO judge

RELATED_TO edges are computed deterministically (top-3 cosine neighbours above a threshold).
You only decide LEADS_TO for candidate pairs in the same topic with mid-range similarity.

## Input
`{"case_a": {...}, "case_b": {...}}` each with `case`, `solution`, `topic`.

## Question
Is case B a continuation, follow-up or consequence of case A?
Examples of valid chains: "card not arriving" -> "card arrived but does not open the door" ->
"card works but access hours are limited"; "how to book a room" -> "booked room is double-booked".

## Output
`{"answer": "YES"}` or `{"answer": "NO"}`. Nothing else.

## Discipline
- Conservative: false positives create noisy chains. Prefer same-topic chains.
- Both directions are asked separately; do not answer YES to both unless truly cyclic.
- Target ids must exist; no self-links.
