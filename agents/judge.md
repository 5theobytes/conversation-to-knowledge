<!-- task: judge -->
# judge — independent scoring of emitted cases (not wired into the offline demo)

For every emitted case, re-read ALL original messages of the source thread (both sides,
original language) and score:

## A. Structural (1-5 each)
1. Initiated by the requester (not an agent broadcast).
2. Solution is a real agent action (not "requester confirmed").
3. `original_question` is a real question (not a reply / ack / agent quote).
4. Anonymisation clean (no names, numbers, dates, service brands).
5. Topic correctly chosen.

## B. Eyeball verdict
`ok` | `minor_issue` | `major_issue` (+ reason): does the case faithfully reflect the thread?
Typical major issues: agent-initiated thread dressed as a question, fabricated solution,
mid-thread reply treated as the opening question, missing context.

A case is an `error` iff any structural criterion < 3 or the eyeball verdict is `major_issue`.

## Output
One JSON line per case: `{"case_id", "scores": {...}, "verdict", "reason"}` plus a summary
with precision (= 1 - errors / cases). Errors feed the supervisor's next iteration and the
`ERRORS_LOG`; every post-filter rule names the error class that drove it.
