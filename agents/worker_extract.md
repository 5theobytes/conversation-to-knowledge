<!-- task: extract -->
# worker_extract — turn one pre-qualified thread into 0..N sub-cases

## Input
Thread JSON (messages with `msg_id`, `from_role`, `text`), plus the pre-qualifier's
`topic_hint`, `question_paraphrase` (a starting hint, refine it), `sensitive_topic_signal`
and `known_names` (must never appear in the output).

## Output
```json
{"cases": [{
  "topic": "snake_case from the whitelist",
  "case": "2-4 English sentences. The REQUESTER's situation only. Generalised, anonymised.",
  "solution": "2-4 English sentences. What the AGENT actually did or said. Never null for unresolved: write what the agent committed to.",
  "status": "resolved | informational | escalated | unresolved",
  "original_question": "verbatim requester text in its ORIGINAL language, volatile values replaced by placeholders",
  "original_question_lang": "en|ru|th|...",
  "evidence_msg_ids": [/* every msg_id the case and solution are derived from */],
  "volatile_kinds": ["phone", "amount", "date", ...],
  "escalation_flag": true,
  "initiated_by": "requester | agent_action_triggered"
}], "drop_reason": "only when cases is empty"}
```

## Anchor rules
- The anchor is the FIRST substantive requester message. Ack-first messages are not anchors;
  scan forward. If an agent instruction precedes the only substantive requester turn, drop
  as `AGENT_INITIATED`.
- Reminders, "yes but..." reactions and status statements ("day off today") cannot be anchors.
- `original_question` must be a verbatim or near-verbatim substring of a requester message in
  `evidence_msg_ids`. Never synthesise a question from the topic.

## Solution rules
- Pick the LAST substantive agent action or commitment, not the first holding ack
  ("let me check", "on it").
- Action verb + concrete object. Forbidden: "handled the request", "provided guidance".
- Never derive a solution from a template. If no agent turn names an action, status is
  `unresolved` and the solution states that explicitly.
- "The requester confirmed/sent/agreed" is NOT a solution.
- Paraphrase grounding: "agent arranged/provided/confirmed/explained" only if an agent turn
  contains a matching action.

## Case / solution strict split
The `case` describes the requester's situation and contains NO agent actions (active or
passive voice). Agent actions live in `solution`.

## Anonymisation (hard)
Names -> `<person_name>`; phones -> `<phone_number>`; card/account numbers -> `<card_number>`;
amounts with currency -> `<amount>`; dates -> `<date>`; e-mails -> `<email>`; addresses ->
`<address>`. Brand names of third-party services -> `<service>`. `volatile_kinds` declares
what was substituted; declaring is not scrubbing.

## Escalation flag
`true` if answering requires: access to the requester's personal records; specific data from
the requester; approval or action beyond a support agent's authority; a transaction or state
change. `false` ONLY when the answer is a generic instruction anyone could give in one reply.
Sensitive topics (`sensitive_topic_signal`) are always `true`.

## Evidence completeness
`evidence_msg_ids` must include every agent turn relevant to the resolution, including
end-of-thread turns and turns from a second agent account.
