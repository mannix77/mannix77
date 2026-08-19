# Data model

The JSON files in `data/` are the source of truth. Everything in `build/` is
generated and safe to delete.

## Ids

`<prefix>:<snake_case_slug>`, enforced by `validate`:

| Node type | Prefix | Example |
|---|---|---|
| pillar | `pillar` | `pillar:how_to_win` |
| concept | `concept` | `concept:wwhtbt` |
| principle | `principle` | `principle:test_the_weakest_link` |
| trap | `trap` | `trap:initiative_list` |
| test | `test` | `test:htw_single_logic` |
| slot | `slot` | `slot:wtp_exclusions` |
| question | `q` | `q:logic_least_believed` |
| source | `src` | `src:wwhtbt` |

## Edges

Most edges are **derived** from reference fields on nodes, so a relationship is
declared once, next to the thing it belongs to. `data/edges.json` carries only
what no field implies.

Derived (field → edge type → permitted targets):

| Field | Edge | Targets |
|---|---|---|
| `pillar` | `IN_PILLAR` | pillar |
| `part_of` | `PART_OF` | concept, pillar |
| `related` | `RELATED_TO` | concept, principle, trap |
| `contrasts_with` | `CONTRASTS_WITH` | concept |
| `confused_with` | `CONFUSED_WITH` | concept |
| `depends_on` | `DEPENDS_ON` | slot |
| `evaluates` | `EVALUATES` | concept |
| `detects` | `DETECTS` | trap |
| `mitigated_by` | `MITIGATED_BY` | test |
| `probes` | `PROBES` | test |
| `covers` | `COVERS` | slot |
| `slots` | `APPLIES_TO` | slot |
| `follow_ups` | `FOLLOW_UP` | question |
| `sources` | `CITES` | source |

Explicit, in `edges.json`: `PRECEDES` (pillar order), `GATES` (a blocking test
suspends a downstream pillar), `PAIRED_WITH`, `PRODUCES`, `FEEDS`, `ENABLES`,
`TREATED_BY`, `VIOLATES` (trap → principle).

## Node shapes

### pillar
`label`, `order` (10-step increments), `summary`, `assess_focus`, `sources`.
`order` must agree with the `PRECEDES` chain — `validate` checks this.

### concept
`label`, optional `aka`, `pillar`, `summary` (what it is), `practitioner_note`
(how it shows up in real strategy work), plus reference fields.

### principle
`statement` (the normative claim), `implication` (what follows for assessment),
`coaching_use` (how to put it to a user as a question).

### trap
`summary`, `signals` (observable, so the agent can spot it), `why_costly`,
`confused_with` (the concept it imitates), `mitigated_by` (tests that catch it),
`coaching_move` (how to surface it without accusing anyone). Every trap must have
at least one `signals` entry and one `mitigated_by` test.

### test
The assessment unit.

| Field | Meaning |
|---|---|
| `statement` | The proposition being checked, phrased so it can be judged |
| `why_it_matters` | What goes wrong when it fails — the agent's explanation to the user |
| `pass_signals` / `fail_signals` | What each verdict looks like in real material |
| `severity` | `blocking` \| `major` \| `minor` |
| `weight` | 1-5, contribution to pillar readiness |
| `evaluates` / `detects` / `slots` | Concepts assessed, traps caught, slots involved |

`blocking` means a `fail` makes downstream assessment premature. Only blocking
tests may appear on the source side of a `GATES` edge.

Gap priority = `severity_rank × weight × (2 if fail else 1)`.

### slot
An element of the **user's** strategy, not of the framework.

`order` (cascade sequence), `required`, `captures` (what belongs here),
`sufficient_when` (what makes it filled rather than partial), `not_sufficient`
(common near-misses), `depends_on` (slots that should be at least partial first).

### question
| Field | Meaning |
|---|---|
| `text` | Asked close to verbatim. Must end in `?` and contain no authoring language |
| `intent` | Why this question, for the agent's own reasoning |
| `kind` | `opening` \| `clarifying` \| `probing` \| `challenge` \| `evidence` \| `reframe` \| `closing` |
| `depth` | 1 surface, 2 probing, 3 hard |
| `probes` | Tests it informs — required; a question that tests nothing is chatter |
| `covers` | Slots it fills |
| `detects` | Traps it would surface |
| `ask_when` | `opening`, `always`, `slot_empty`, `test_fail`, `test_partial`, `trap_hint`, `deep`, `closing` |
| `follow_ups` | Where to go next |

### source
`label` (title), `url`, `kind`, optional `published`, `themes`, plus
`full_text_ingested` (always `false`), `verified` and `verified_on` recording how
the citation was confirmed.

## Strategy state

Not part of the graph — the agent's per-session record. See
`agent/tool_contract.md` for the shape and the rules for maintaining it.

`slot → filled | partial | empty`, `test → pass | partial | fail | unknown`,
plus `evidence`, `trap_hints`, `asked`.

Readiness for a pillar is `Σ(weight × credit) / Σ(weight)` where credit is
1.0 / 0.5 / 0.0 / 0.0. `unknown` scores zero but is reported separately as
coverage, so a low readiness caused by not having looked yet is distinguishable
from one caused by genuine failures.

## Adding a node

1. Write it into the right `data/*.json`.
2. Give it a `pillar` and wire its reference fields.
3. If it is a test, add at least one question that `probes` it.
4. If it is a trap, add `signals`, a `mitigated_by` test, and a question that `detects` it.
5. `PYTHONPATH=src python3 -m graphify validate` must come back clean.
6. `python3 -m unittest discover -s tests -t .`
7. `PYTHONPATH=src python3 -m graphify build`

`validate` will refuse a test no question probes, a required slot no question
covers, and a trap no question detects — the three ways a graph silently stops
being usable by the agent.
