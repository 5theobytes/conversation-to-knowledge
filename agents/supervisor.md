<!-- task: supervisor -->
# supervisor — iteration owner (not wired into the offline demo)

The supervisor runs at the start (`brief`) and end (`decide`) of each iteration of the
extraction pipeline.

## Brief
- Read the previous iteration's judge verdicts, the drop log (`trash.jsonl`) and the
  advisors' notes.
- Write `tasks.json`: per-role constraints for this iteration.
- Verify the pre-qualifier output before extraction starts.

## Decide
- Compare precision / recall / unique valid cases with the previous iteration.
- For each error class: decide whether the fix belongs in a role prompt (memory), in the
  deterministic rule engine, or is a data problem. A rule is added only with a named driver
  case and positive + negative tests.
- Rules of thumb learned the hard way:
  * "replicate, do not add features" once an iteration is clean; measure before changing;
  * avoid the pendulum: a fix that drops half of the output is a worse prompt, not a win;
  * a filter is a safety net; the worker prompt must carry the same constraint;
  * every drop is logged with stage + reason, so recall can be analysed later.

## Definition of done (per deliverable)
A. flat case table with `topic | case | solution | escalation_flag`, placeholders only;
B. utterance index: every case has >= 1 original-language question `{text, lang, ts, thread_id}`;
C. graph with INSTANCE_OF, RESOLVED_BY, RELATED_TO, LEADS_TO, MENTIONS_VOLATILE;
D. traceable logs (drops, verdicts, rule versions).
