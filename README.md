# Strategy Practitioner Graph

A queryable knowledge graph of the strategy practitioner method developed across
Roger L. Martin's *Strategy Practitioner Insights* series on Substack, built to
drive a **Socratic coaching agent**.

The agent's job is narrow and deliberate: it **assesses** a user's strategy and
**asks questions** so the user can improve it themselves. It never writes,
drafts, or completes the strategy.

```
                        ┌────────────────────────┐
   user's strategy ───► │  assess  (44 tests)    │ ──► readiness + gaps
                        └───────────┬────────────┘
                                    │
                        ┌───────────▼────────────┐
                        │  ask  (96 questions)   │ ──► one or two questions,
                        └───────────┬────────────┘      each traced to a gap
                                    │
                          user answers ──► state updated ──► loop
```

## What is in the graph

336 nodes, 1,636 edges, across eight node types:

| Type | Count | What it is |
|---|---|---|
| `pillar` | 11 | The areas a strategy has to answer for, in assessment order |
| `concept` | 59 | The vocabulary — Where-to-Play, Promise to the Customer, barriers to choice… |
| `principle` | 33 | Normative rules, each with how to use it in coaching |
| `trap` | 27 | Failure patterns, with observable signals and the coaching move for each |
| `test` | 44 | Checkable propositions with pass/fail signals, severity and weight |
| `slot` | 31 | The elements of the *user's* strategy the agent tracks state for |
| `question` | 96 | The coaching questions, each probing a test and covering a slot |
| `source` | 35 | Cited pieces from the series, by title and URL |

The eleven pillars, in the order the agent works them:

`definition` → `winning_aspiration` → `where_to_play` → `customer` →
`how_to_win` → `competition` → `capabilities` → `management_systems` →
`coherence` → `logic` → `adoption`

## Quickstart

Zero dependencies — Python 3.11+ standard library only.

```bash
# integrity-check the data and build the artefacts
PYTHONPATH=src python3 -m graphify validate
PYTHONPATH=src python3 -m graphify build        # -> build/graph.{sqlite,json,cypher}

# explore
PYTHONPATH=src python3 -m graphify stats
PYTHONPATH=src python3 -m graphify show concept:wwhtbt
PYTHONPATH=src python3 -m graphify show trap:initiative_list
PYTHONPATH=src python3 -m graphify pillar pillar:how_to_win
PYTHONPATH=src python3 -m graphify search "promise to the customer"
PYTHONPATH=src python3 -m graphify corpus

# run the assessment path over the worked example
PYTHONPATH=src python3 -m graphify prescreen examples/sample_strategy.md
PYTHONPATH=src python3 -m graphify assess    examples/session_state.json
PYTHONPATH=src python3 -m graphify next      examples/session_state.json --limit 3
PYTHONPATH=src python3 -m graphify plan      examples/session_state.json --rounds 4

# the bundle an agent loads once per session
PYTHONPATH=src python3 -m graphify agent-context

# tests
python3 -m unittest discover -s tests -t .
```

On the sample strategy, `next` leads with the two blocking failures — no named
desired customer action, and no must-be-true conditions written down — which is
the intended behaviour: everything downstream of those is premature.

## How assessment works

The split is deliberate:

- **The graph decides structure.** Which tests apply, what each is worth, what
  gates what, which questions follow from which gap, and in what order. Fully
  deterministic — the same state always produces the same queue, so every
  question the agent asks is traceable rather than improvised.
- **The agent decides verdicts.** Judging whether a stated way of winning really
  resolves to a cost advantage is a reading task. `assess.py` never guesses it;
  it consumes `pass` / `partial` / `fail` / `unknown` plus the evidence behind
  each one.

`prescreen()` is the one heuristic component: cheap regexes over pasted text that
flag passages worth reading closely. Every hint is labelled `unverified` and can
never become a verdict on its own.

Question priority: failed blocking test → missing required slot (cascade order,
respecting prerequisites) → weak test by severity × weight → suspected trap →
follow-up depth → unexamined pillar.

## Repository layout

```
data/                 the source of truth — hand-editable JSON
  pillars.json  concepts.json  principles.json  traps.json
  tests.json    slots.json     questions.json   sources.json
  edges.json          relationships no node field implies
src/graphify/
  model.py            load, derive edges, validate integrity
  build.py            sqlite + json + cypher artefacts
  query.py            retrieval surface for the agent
  assess.py           state, prescreen, readiness scoring
  interview.py        question selection policy
  cli.py              command line interface
agent/
  system_prompt.md    the coach's instructions, including the one rule
  coaching_protocol.md session mechanics and failure modes
  tool_contract.md    the functions a runtime should expose
examples/             a deliberately bad strategy + a mid-session state
tools/refresh_corpus.py  extend the source index (metadata only)
tests/                47 tests
```

Most edges are **derived** from reference fields on the nodes (`probes`,
`detects`, `mitigated_by`, `sources`…) rather than hand-listed, so the data stays
readable and the edge list cannot drift out of sync. `validate` enforces
referential integrity, id conventions, required fields, that every test is probed
by some question, that every required slot is covered, that every trap is
detectable, and that the `PRECEDES` chain agrees with the pillars' `order` fields.

## Extending it

Add a node to the relevant `data/*.json`, wire it up with reference fields, then:

```bash
PYTHONPATH=src python3 -m graphify validate   # must be clean
python3 -m unittest discover -s tests -t .
PYTHONPATH=src python3 -m graphify build
```

Two invariants the tests enforce, both worth keeping:

1. Every question ends in a question mark and contains no authoring language
   (`test_questions_do_not_author`). A question that suggests its own answer has
   crossed the line the agent exists to hold.
2. Every test carries both pass and fail signals. A test the agent cannot apply
   consistently is worse than no test.

## Provenance, and an honest limit

**The concept content here is original writing.** Each node is an abstraction of
a theme developed in the series — written for this repository, in its own words —
with citations pointing to where the theme is developed. No article text is
reproduced, stored, or excerpted anywhere in this repo, and `tools/refresh_corpus.py`
collects metadata only (title, URL, date) by design.

**The source index is partial.** The environment this was built in blocks
outbound access to `substack.com`, `rogerlmartin.com` and `medium.com` at the
network proxy, so full-text retrieval and archive crawling were not possible.
The 35 cited pieces were verified through web search and confirmed to exist by
title and URL; the series itself ran weekly from October 2020 to early 2026 and
is considerably larger. `tools/refresh_corpus.py --dry-run` will index the rest
from anywhere with network access.

What this means in practice: the *method* encoded here — the pillars, tests,
traps and questions — is complete enough to run real coaching sessions, because
it rests on the framework as a whole rather than on any single post. The
*citation coverage* is the part that improves when the refresh tool can run.

Original material: [Strategy Practitioner Insights](https://rogerlmartin.substack.com/)
by Roger L. Martin, and the author's own
[series archive](https://rogerlmartin.com/archive/playing-to-win-practitioner-insights-series).
This repository is an independent study aid and is not affiliated with or
endorsed by the author.
