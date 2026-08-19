# Tool contract

The functions an agent runtime should expose. Each maps to one call in
`src/graphify/`. Nothing here mutates the graph; the only mutable thing in a
session is the strategy state, which the agent owns.

## Session setup

### `load_context() -> object`
`cli.agent_context(graph)`. Load once per session. Returns the pillars in
assessment order, every principle, every trap with its observable signals, every
test with its pass/fail signals, and every slot with what counts as sufficient.
This is the agent's working reference — roughly the size of a long prompt, so
load it once and keep it.

## Reading the graph

### `search(term, limit=12, types=None) -> list`
`query.search`. Substring search across labels, aliases, summaries and question
text. Use when the user names a concept and you want the graph's node for it.

### `pillar_pack(pillar_id) -> object`
`query.pillar_pack`. Everything for one area: concepts, principles, traps, tests
ordered by severity, slots in order, questions by depth. Use when the
conversation settles into one area.

### `concept_pack(concept_id) -> object`
`query.concept_pack`. A concept, what it is part of, what relates to it, the
tests that evaluate it, the traps confused with it, and its citations. Use when
the user asks what something means.

### `test_pack(test_id)` / `trap_pack(trap_id) -> object`
`query.test_pack`, `query.trap_pack`. A single test with the questions that probe
it and the traps it catches; a single trap with its signals, the tests that catch
it, the principle it violates, and its citations.

### `explain(a, b) -> object`
`query.explain`. Shortest path between two nodes. Use to justify a question: why
does asking about channel bear on their How-to-Win?

### `corpus() -> list`
`query.corpus`. The indexed source material with titles, URLs and citation
counts. Use when the user asks where something comes from, or for further reading.

## Assessing

### `prescreen(text) -> list`
`assess.prescreen`. Cheap regex hints over pasted material. **Every result is
unverified.** Read the passage before acting on it, and discard hints that do not
hold up — a document can say "moat" and still have a sound account of renewal.

### `assess(state) -> object`
`assess.assess`. Returns per-pillar readiness and coverage, blocking failures,
a priority-ranked gap list, suspected traps, and any pillars gated by an upstream
blocking failure. Call after each meaningful update to the state.

### `validate_state(state) -> list`
`assess.validate_state`. Catches unknown ids and bad enum values before they
propagate. Call whenever you construct state from anything other than your own
previous output.

## Asking

### `next_questions(state, limit=3) -> list`
`interview.next_questions`. The ranked queue, each entry carrying `reason` and
`because` so you can tell the user why you are asking. **Ask one or two.** The
`limit` is how many the policy hands you to choose from, not how many to fire.

### `follow_ups(question_id) -> list`
`query.follow_ups`. Where to go once a question has been answered.

### `coverage_report(state) -> object`
`interview.coverage_report`. Asked versus available, by pillar. Use to notice
that you have spent the whole session in one area.

### `session_plan(state, rounds=5) -> list`
`interview.session_plan`. A preview of the line of questioning, assuming answers
land. For inspecting the policy — not a script to read aloud.

## Strategy state

The one mutable object. Shape:

```json
{
  "slots":      { "slot:wtp_customers": "filled|partial|empty" },
  "verdicts":   { "test:htw_single_logic": "pass|partial|fail|unknown" },
  "evidence":   { "test:htw_single_logic": "why you judged it that way" },
  "trap_hints": ["trap:initiative_list"],
  "asked":      ["q:open_what_is_it"]
}
```

Rules the agent must hold to:

- A verdict is only set from something the user said or wrote. Absence of
  evidence is `unknown`, not `fail` — unless the test is *about* the absence
  (a missing exclusion genuinely fails `test:wtp_has_exclusions`).
- Always write `evidence` alongside a verdict. A verdict you cannot justify next
  turn will read as arbitrary to the user, because it is.
- `trap_hints` are suspicions. Promote a suspicion to a finding only by way of the
  test that catches it, and drop it once the user's answer clears it.
- Append to `asked` when a question is actually put to the user, not when the
  policy offers it. Otherwise the queue starves.
- Persist the state between turns. It is the record of the engagement, and it is
  what makes the second session more useful than the first.
